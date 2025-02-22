from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from models import db, User, Event, Booking, Train, TrainBooking, Station, Flight, FlightBooking, Airport, Airline, Wallet, Transaction
import os
from datetime import datetime
from dotenv import load_dotenv
import requests
import json
import random
import string
from utils.irctc_api import IRCTCApi
from utils.flight_api import FlightAPI
from werkzeug.utils import secure_filename
from functools import wraps
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DateTimeField, IntegerField, SelectField, BooleanField, FloatField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError
import razorpay
from io import StringIO
import csv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_timeout': 900,
    'pool_size': 10,
    'max_overflow': 5,
    'connect_args': {
        'sslmode': 'require',
        'connect_timeout': 10
    }
}

# Configure upload folder
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Configure allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize APIs
irctc_api = IRCTCApi()
flight_api = FlightAPI()

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID'), os.getenv('RAZORPAY_KEY_SECRET')))

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Custom Jinja2 filters
@app.template_filter('min_price')
def min_price_filter(price_tiers):
    """Get the minimum price from a list of price tiers."""
    if not price_tiers:
        return 0.00
    # Handle string case
    if isinstance(price_tiers, str):
        try:
            price_tiers = json.loads(price_tiers)
        except json.JSONDecodeError:
            return 0.00
    # Handle list case
    if isinstance(price_tiers, list):
        if not price_tiers:
            return 0.00
        return min(float(tier.get('price', 0)) for tier in price_tiers)
    return 0.00

@app.template_filter('format_date')
def format_date(value):
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        dt = value
    return dt.strftime('%B %d, %Y')

@app.template_filter('format_time')
def format_time(value):
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        dt = value
    return dt.strftime('%I:%M %p')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    events = Event.query.filter(Event.start_date > datetime.utcnow()).order_by(Event.start_date).all()
    return render_template('index.html', events=events)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        
        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/event/<int:event_id>')
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template('event_detail.html', event=event)

@app.route('/book/<int:event_id>', methods=['GET', 'POST'])
@login_required
def book_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        try:
            num_tickets = int(request.form.get('num_tickets', 0))
            ticket_tier = request.form.get('ticket_tier')
            
            # Get attendee details
            attendee_details = {
                'name': request.form.get('attendee_name'),
                'email': request.form.get('attendee_email'),
                'phone': request.form.get('attendee_phone')
            }
            
            # Add additional fields if enabled in event settings
            if event.ticket_fields.get('age', {}).get('enabled'):
                attendee_details['age'] = request.form.get('attendee_age')
                
            if event.ticket_fields.get('gender', {}).get('enabled'):
                attendee_details['gender'] = request.form.get('attendee_gender')
                
            if event.ticket_fields.get('id_proof', {}).get('enabled'):
                attendee_details['id_proof'] = {
                    'type': request.form.get('attendee_id_type'),
                    'number': request.form.get('attendee_id_number')
                }
                
            if event.ticket_fields.get('address', {}).get('enabled'):
                attendee_details['address'] = request.form.get('attendee_address')
                
            # Handle custom fields
            custom_fields = {}
            for field in event.ticket_fields.get('custom_fields', []):
                field_name = field['name']
                custom_fields[field_name] = request.form.get(f'attendee_custom_{field_name}')
            if custom_fields:
                attendee_details['custom_fields'] = custom_fields
            
            # Validate required fields
            required_fields = []
            for field, config in event.ticket_fields.items():
                if field == 'custom_fields':
                    continue
                if isinstance(config, dict) and config.get('required') and config.get('enabled'):
                    required_fields.append(field)
            
            for field in required_fields:
                if field == 'id_proof':
                    if not attendee_details.get('id_proof', {}).get('type') or not attendee_details.get('id_proof', {}).get('number'):
                        flash('ID proof type and number are required')
                        return redirect(url_for('book_event', event_id=event_id))
                elif not attendee_details.get(field):
                    flash(f'{field.title()} is required')
                    return redirect(url_for('book_event', event_id=event_id))
            
            # Validate custom fields
            for field in event.ticket_fields.get('custom_fields', []):
                if field.get('required') and not custom_fields.get(field['name']):
                    flash(f'{field["label"]} is required')
                    return redirect(url_for('book_event', event_id=event_id))
            
            if num_tickets <= 0:
                flash('Please select at least one ticket')
                return redirect(url_for('book_event', event_id=event_id))
            
            # Start transaction
            try:
                # Lock the event row for update
                event = Event.query.with_for_update().get(event_id)
                if not event:
                    flash('Event not found')
                    return redirect(url_for('book_event', event_id=event_id))
                
                if event.status != 'published':
                    flash('This event is not available for booking')
                    return redirect(url_for('book_event', event_id=event_id))
                
                if num_tickets > event.available_seats:
                    flash('Not enough seats available')
                    return redirect(url_for('book_event', event_id=event_id))
                
                # Find the selected price tier
                selected_tier = next((tier for tier in event.price_tiers if tier['id'] == ticket_tier), None)
                if not selected_tier:
                    flash('Invalid ticket tier selected')
                    return redirect(url_for('book_event', event_id=event_id))
                    
                if num_tickets > selected_tier['quantity']:
                    flash('Not enough tickets available in this tier')
                    return redirect(url_for('book_event', event_id=event_id))
                
                # Calculate total price and create booking
                base_price = num_tickets * selected_tier['price']
                gst = base_price * 0.18  # 18% GST
                total_price = base_price + gst
                booking = Booking(
                    user_id=current_user.id,
                    event_id=event_id,
                    num_tickets=num_tickets,
                    total_price=total_price,
                    tier_id=ticket_tier,
                    status='pending',  # Set initial status as pending until payment
                    attendee_details=attendee_details
                )
                
                # Generate ticket code and codes
                booking.ticket_code = booking.generate_ticket_code()
                if event.show_qr_code:
                    booking.qr_code = booking.generate_qr_code()
                if event.show_barcode:
                    booking.barcode = booking.generate_barcode()
                
                # Update available seats and tier quantity
                event.available_seats -= num_tickets
                selected_tier['quantity'] -= num_tickets
                event.price_tiers = [tier if tier['id'] != ticket_tier else selected_tier for tier in event.price_tiers]
                
                # Add booking and commit transaction
                db.session.add(booking)
                db.session.commit()
                
                # Redirect to payment processing
                return redirect(url_for('process_payment', booking_type='event', booking_id=booking.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error processing booking: {str(e)}')
                return redirect(url_for('book_event', event_id=event_id))
                
        except ValueError:
            flash('Invalid ticket quantity')
            return redirect(url_for('book_event', event_id=event_id))
    
    return render_template('book_event.html', event=event)

@app.route('/my-bookings')
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    total_spent = sum(booking.total_price for booking in bookings)
    return render_template('my_bookings.html', bookings=bookings, total_spent=total_spent)

# Train Booking Routes
@app.route('/trains')
def trains():
    source = request.args.get('source')
    destination = request.args.get('destination')
    date = request.args.get('date')
    
    if source and destination and date:
        try:
            trains = irctc_api.search_trains(source, destination, date)
            return render_template('trains/search.html', trains=trains, source=source, destination=destination, date=date)
        except Exception as e:
            flash('Error fetching train information. Please try again.')
            return render_template('trains/search.html')
    
    # Get popular stations for the form
    popular_stations = Station.query.limit(10).all()
    return render_template('trains/search.html', popular_stations=popular_stations)

@app.route('/trains/<train_number>')
def train_detail(train_number):
    try:
        date = request.args.get('date')
        if not date:
            flash('Please select a journey date.')
            return redirect(url_for('trains'))
        
        # Get seat availability
        availability = irctc_api.check_availability(train_number, date)
        
        # Get train details from our database or IRCTC API
        train = Train.query.filter_by(train_number=train_number).first()
        if not train:
            # If train not in our database, get from IRCTC API
            train_data = irctc_api.search_trains(None, None, date)
            train = next((t for t in train_data if t['number'] == train_number), None)
            if not train:
                flash('Train information not found.')
                return redirect(url_for('trains'))
        
        return render_template('trains/detail.html', train=train, availability=availability, journey_date=date)
    except Exception as e:
        flash('Error fetching train details. Please try again.')
        return redirect(url_for('trains'))

@app.route('/trains/<train_number>/book', methods=['GET', 'POST'])
@login_required
def book_train(train_number):
    if request.method == 'POST':
        try:
            # Prepare booking data
            booking_data = {
                'trainNumber': train_number,
                'journeyDate': request.form.get('journey_date'),
                'travelClass': request.form.get('travel_class'),
                'passengers': []
            }
            
            # Process passenger details
            for i in range(int(request.form.get('num_passengers', 1))):
                passenger = {
                    'name': request.form.get(f'passengers[{i}][name]'),
                    'age': int(request.form.get(f'passengers[{i}][age]')),
                    'gender': request.form.get(f'passengers[{i}][gender]'),
                    'idType': request.form.get(f'passengers[{i}][id_type]'),
                    'idNumber': request.form.get(f'passengers[{i}][id_number]')
                }
                booking_data['passengers'].append(passenger)
            
            # Add contact details
            booking_data['contactEmail'] = request.form.get('contact_email')
            booking_data['contactPhone'] = request.form.get('contact_phone')
            
            # Make booking through IRCTC API
            response = irctc_api.book_ticket(booking_data)
            
            if response.get('error'):
                flash(f'Booking failed: {response["error"]}')
                return redirect(url_for('train_detail', train_number=train_number))
            
            # Create booking record in our database
            booking = TrainBooking(
                user_id=current_user.id,
                train_number=train_number,
                pnr=response.get('pnr'),
                travel_class=booking_data['travelClass'],
                journey_date=datetime.strptime(booking_data['journeyDate'], '%Y-%m-%d'),
                num_passengers=len(booking_data['passengers']),
                total_fare=response.get('totalFare'),
                passengers=booking_data['passengers'],
                contact_email=booking_data['contactEmail'],
                contact_phone=booking_data['contactPhone'],
                payment_status='pending'
            )
            
            db.session.add(booking)
            db.session.commit()
            
            flash(f'Booking successful! Your PNR number is {booking.pnr}')
            return redirect(url_for('train_booking_confirmation', booking_id=booking.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error processing your booking. Please try again.')
            return redirect(url_for('train_detail', train_number=train_number))
    
    return render_template('trains/booking.html', train_number=train_number)

@app.route('/trains/bookings/<int:booking_id>')
@login_required
def train_booking_confirmation(booking_id):
    booking = TrainBooking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        flash('Unauthorized access.')
        return redirect(url_for('trains'))
    
    # Get latest PNR status
    pnr_status = irctc_api.get_pnr_status(booking.pnr)
    return render_template('trains/confirmation.html', booking=booking, pnr_status=pnr_status)

@app.route('/trains/bookings')
@login_required
def my_train_bookings():
    bookings = TrainBooking.query.filter_by(user_id=current_user.id).order_by(TrainBooking.booking_date.desc()).all()
    
    # Get PNR status for all bookings
    for booking in bookings:
        booking.status = irctc_api.get_pnr_status(booking.pnr)
    
    return render_template('trains/my_bookings.html', bookings=bookings)

@app.route('/api/stations/search')
def search_stations():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    try:
        # First try to search in our database
        db_stations = Station.query.filter(
            (Station.code.ilike(f'%{query}%')) |
            (Station.name.ilike(f'%{query}%'))
        ).limit(10).all()
        
        if db_stations:
            return jsonify([{
                'code': station.code,
                'name': station.name,
                'state': station.state
            } for station in db_stations])
        
        # If no results in database, try IRCTC API
        stations = irctc_api.search_stations(query)
        return jsonify(stations)
    except Exception as e:
        print(f"Station search error: {str(e)}")
        return jsonify([])

# Flight Booking Routes
@app.route('/flights')
def flights():
    return render_template('flights/index.html')

@app.route('/api/airports/search')
def search_airports():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    airports = Airport.query.filter(
        (Airport.code.ilike(f'%{query}%')) |
        (Airport.name.ilike(f'%{query}%')) |
        (Airport.city.ilike(f'%{query}%'))
    ).limit(10).all()
    
    return jsonify([{
        'iata': airport.code,
        'name': airport.name,
        'city': airport.city,
        'state': airport.state,
        'country': airport.country
    } for airport in airports])

@app.route('/api/flights/search')
def search_flights():
    origin = request.args.get('origin')
    destination = request.args.get('destination') 
    date = request.args.get('date')
    
    if not all([origin, destination, date]):
        return jsonify({'error': 'Missing required parameters'}), 400
        
    try:
        # First check our database
        flights = Flight.query.join(Flight.origin_airport).join(Flight.destination_airport).filter(
            Airport.code == origin,
            Airport.code == destination,
            Flight.departure_time >= datetime.strptime(date, '%Y-%m-%d').date()
        ).all()
        
        # If no flights found, search via API
        if not flights:
            flights = flight_api.search_flights(origin, destination, date)
            
        return jsonify([flight.to_dict() for flight in flights])
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/flights/<int:flight_id>')
def flight_details(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    return render_template('flights/details.html', flight=flight)

@app.route('/flights/<int:flight_id>/book', methods=['POST'])
@login_required
def book_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    
    # Get booking details from form
    passengers = json.loads(request.form.get('passengers', '[]'))
    cabin_class = request.form.get('cabin_class')
    
    if not passengers:
        flash('Please add at least one passenger', 'error')
        return redirect(url_for('flight_details', flight_id=flight_id))
        
    try:
        # Create booking
        booking = FlightBooking(
            user_id=current_user.id,
            flight_id=flight.id,
            cabin_class=cabin_class,
            passengers=passengers,
            status='pending',
            booking_reference=''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        )
        
        db.session.add(booking)
        db.session.commit()
        
        # Redirect to payment page
        return redirect(url_for('process_payment', booking_type='flight', booking_id=booking.id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error booking flight: {str(e)}', 'error')
        return redirect(url_for('flight_details', flight_id=flight_id))

@app.route('/my-bookings/flights')
@login_required
def my_flight_bookings():
    bookings = FlightBooking.query.filter_by(user_id=current_user.id).all()
    return render_template('flights/my_bookings.html', bookings=bookings)

@app.route('/api/flight-bookings/<booking_reference>/status')
def flight_booking_status(booking_reference):
    booking = FlightBooking.query.filter_by(booking_reference=booking_reference).first_or_404()
    
    try:
        # Check status via API if needed
        status = flight_api.check_booking_status(booking_reference)
        
        if status != booking.status:
            booking.status = status
            db.session.commit()
            
        return jsonify({
            'status': booking.status,
            'flight': {
                'flight_number': booking.flight.flight_number,
                'departure_time': booking.flight.departure_time.isoformat(),
                'arrival_time': booking.flight.arrival_time.isoformat()
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/flight-bookings/<booking_reference>/cancel', methods=['POST'])
@login_required
def cancel_flight_booking(booking_reference):
    booking = FlightBooking.query.filter_by(
        booking_reference=booking_reference,
        user_id=current_user.id
    ).first_or_404()
    
    try:
        # Cancel via API if needed
        flight_api.cancel_booking(booking_reference)
        
        booking.status = 'cancelled'
        booking.cancellation_time = datetime.utcnow()
        db.session.commit()
        
        flash('Flight booking cancelled successfully', 'success')
        
    except Exception as e:
        flash(f'Error cancelling booking: {str(e)}', 'error')
        
    return redirect(url_for('my_flight_bookings'))

# Add this function to initialize sample stations
def init_sample_stations():
    sample_stations = [
        {'code': 'NDLS', 'name': 'New Delhi', 'state': 'Delhi', 'zone': 'Northern'},
        {'code': 'BCT', 'name': 'Mumbai Central', 'state': 'Maharashtra', 'zone': 'Western'},
        {'code': 'MAS', 'name': 'Chennai Central', 'state': 'Tamil Nadu', 'zone': 'Southern'},
        {'code': 'HWH', 'name': 'Howrah Junction', 'state': 'West Bengal', 'zone': 'Eastern'},
        {'code': 'SBC', 'name': 'Bangalore City', 'state': 'Karnataka', 'zone': 'South Western'},
        {'code': 'CSMT', 'name': 'Mumbai CST', 'state': 'Maharashtra', 'zone': 'Central'},
        {'code': 'ASR', 'name': 'Amritsar Junction', 'state': 'Punjab', 'zone': 'Northern'},
        {'code': 'JP', 'name': 'Jaipur Junction', 'state': 'Rajasthan', 'zone': 'North Western'},
        {'code': 'ADI', 'name': 'Ahmedabad Junction', 'state': 'Gujarat', 'zone': 'Western'},
        {'code': 'PNQ', 'name': 'Pune Junction', 'state': 'Maharashtra', 'zone': 'Central'}
    ]
    
    for station_data in sample_stations:
        if not Station.query.filter_by(code=station_data['code']).first():
            station = Station(**station_data)
            db.session.add(station)
    
    try:
        db.session.commit()
    except Exception as e:
        print(f"Error adding sample stations: {str(e)}")
        db.session.rollback()

# Add this function to initialize sample airports
def init_sample_airports():
    sample_airports = [
        {'code': 'DEL', 'name': 'Indira Gandhi International Airport', 'city': 'New Delhi', 'state': 'Delhi', 'country': 'India'},
        {'code': 'BOM', 'name': 'Chhatrapati Shivaji International Airport', 'city': 'Mumbai', 'state': 'Maharashtra', 'country': 'India'},
        {'code': 'MAA', 'name': 'Chennai International Airport', 'city': 'Chennai', 'state': 'Tamil Nadu', 'country': 'India'},
        {'code': 'BLR', 'name': 'Kempegowda International Airport', 'city': 'Bengaluru', 'state': 'Karnataka', 'country': 'India'},
        {'code': 'HYD', 'name': 'Rajiv Gandhi International Airport', 'city': 'Hyderabad', 'state': 'Telangana', 'country': 'India'},
        {'code': 'CCU', 'name': 'Netaji Subhas Chandra Bose International Airport', 'city': 'Kolkata', 'state': 'West Bengal', 'country': 'India'},
        {'code': 'COK', 'name': 'Cochin International Airport', 'city': 'Kochi', 'state': 'Kerala', 'country': 'India'},
        {'code': 'PNQ', 'name': 'Pune Airport', 'city': 'Pune', 'state': 'Maharashtra', 'country': 'India'},
        {'code': 'AMD', 'name': 'Sardar Vallabhbhai Patel International Airport', 'city': 'Ahmedabad', 'state': 'Gujarat', 'country': 'India'},
        {'code': 'GOI', 'name': 'Dabolim Airport', 'city': 'Goa', 'state': 'Goa', 'country': 'India'}
    ]
    
    for airport_data in sample_airports:
        if not Airport.query.filter_by(code=airport_data['code']).first():
            airport = Airport(**airport_data)
            db.session.add(airport)
    
    try:
        db.session.commit()
    except Exception as e:
        print(f"Error adding sample airports: {str(e)}")
        db.session.rollback()

def host_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_host:
            flash('You need to be registered as an event host to access this page.')
            return redirect(url_for('become_host'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/become-host', methods=['GET', 'POST'])
@login_required
def become_host():
    if current_user.is_host:
        return redirect(url_for('host_dashboard'))
        
    if request.method == 'POST':
        host_info = {
            'organization': request.form.get('organization'),
            'website': request.form.get('website'),
            'phone': request.form.get('phone'),
            'address': request.form.get('address'),
            'description': request.form.get('description')
        }
        
        current_user.is_host = True
        current_user.host_info = host_info
        db.session.commit()
        
        flash('Congratulations! You are now registered as an event host.')
        return redirect(url_for('host_dashboard'))
        
    return render_template('events/become_host.html')

@app.route('/host/dashboard')
@login_required
@host_required
def host_dashboard():
    # Get all events for this host
    events = Event.query.filter_by(host_id=current_user.id).order_by(Event.created_at.desc()).all()
    
    # Get upcoming events (events that haven't ended yet)
    now = datetime.utcnow()
    upcoming_events = [e for e in events if e.end_date > now]
    
    # Calculate statistics
    total_revenue = sum(b.total_price for e in events for b in e.bookings if b.status == 'completed')
    total_tickets = sum(len([b for b in e.bookings if b.status == 'completed']) for e in events)
    total_capacity = sum(e.total_seats for e in events)
    total_attendees = sum(len([b for b in e.bookings if b.check_in_status]) for e in events)
    
    # Get recent activities (last 10)
    recent_activities = []
    
    # Add booking activities
    for event in events:
        for booking in event.bookings:
            recent_activities.append({
                'type': 'booking',
                'message': f'New booking for {event.name}',
                'timestamp': booking.booking_date,
                'event': event
            })
    
    # Add event updates
    for event in events:
        if event.updated_at and event.updated_at > event.created_at:
            recent_activities.append({
                'type': 'event_update',
                'message': f'Updated event: {event.name}',
                'timestamp': event.updated_at,
                'event': event
            })
        if event.status == 'published':
            recent_activities.append({
                'type': 'event_publish',
                'message': f'Published event: {event.name}',
                'timestamp': event.created_at,
                'event': event
            })
    
    # Sort activities by timestamp and get last 10
    recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)
    recent_activities = recent_activities[:10]
    
    stats = {
        'total_events': len(events),
        'active_events': len([e for e in events if e.status == 'published' and e.end_date > now]),
        'published_events': len([e for e in events if e.status == 'published']),
        'total_tickets': total_tickets,
        'total_capacity': total_capacity,
        'total_revenue': total_revenue,
        'total_attendees': total_attendees,
        'ticket_utilization': (total_tickets / total_capacity * 100) if total_capacity > 0 else 0
    }
    
    return render_template('events/host_dashboard.html', 
                         events=events,
                         upcoming_events=upcoming_events[:5],  # Show only next 5 events
                         stats=stats,
                         recent_activities=recent_activities)

@app.route('/host/events')
@login_required
@host_required
def host_events():
    events = Event.query.filter_by(
        host_id=current_user.id,
        parent_id=None  # Only main events
    ).order_by(Event.created_at.desc()).all()
    return render_template('events/event_list.html', events=events)

class EventForm(FlaskForm):
    name = StringField('Event Name', validators=[DataRequired(), Length(min=3, max=200)])
    description = TextAreaField('Description', validators=[DataRequired()])
    event_type = SelectField('Event Type', choices=[
        ('movie', 'Movie'),
        ('concert', 'Concert'),
        ('sports', 'Sports'),
        ('theater', 'Theater'),
        ('other', 'Other')
    ], validators=[DataRequired()])
    start_date = DateTimeField('Start Date', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_date = DateTimeField('End Date', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    venue = StringField('Venue', validators=[DataRequired(), Length(max=200)])
    venue_address = StringField('Venue Address', validators=[DataRequired(), Length(max=500)])
    total_seats = IntegerField('Total Seats', validators=[DataRequired(), NumberRange(min=1)])
    
    def validate_start_date(self, field):
        if field.data < datetime.now():
            raise ValidationError('Start date cannot be in the past')
    
    def validate_end_date(self, field):
        if field.data <= self.start_date.data:
            raise ValidationError('End date must be after start date')

@app.route('/host/events/new', methods=['GET', 'POST'])
@login_required
@host_required
def new_event():
    form = EventForm()
    
    if request.method == 'POST':
        try:
            # Get the action (publish or draft)
            action = request.form.get('action', 'draft')
            
            # Process ticket tiers
            tier_names = request.form.getlist('tier_names[]')
            tier_prices = request.form.getlist('tier_prices[]')
            tier_quantities = request.form.getlist('tier_quantities[]')
            
            if not tier_names or not tier_prices or not tier_quantities:
                flash('At least one price tier is required')
                return redirect(url_for('new_event'))
            
            # Validate ticket quantities
            total_seats = int(request.form.get('total_seats', 0))
            total_tier_quantities = sum(int(qty) for qty in tier_quantities)
            
            if total_tier_quantities > total_seats:
                flash('Sum of tier quantities cannot exceed total seats')
                return redirect(url_for('new_event'))
            
            # Combine into price_tiers list
            price_tiers = []
            for i in range(len(tier_names)):
                try:
                    price = float(tier_prices[i])
                    quantity = int(tier_quantities[i])
                    if price <= 0:
                        flash('Price must be greater than 0')
                        return redirect(url_for('new_event'))
                    if quantity <= 0:
                        flash('Quantity must be greater than 0')
                        return redirect(url_for('new_event'))
                except ValueError:
                    flash('Invalid price or quantity value')
                    return redirect(url_for('new_event'))
                    
                price_tiers.append({
                    'id': f'tier_{i+1}',
                    'name': tier_names[i],
                    'price': price,
                    'quantity': quantity
                })
            
            # Set default venue coordinates if not provided
            venue_coordinates = {
                'lat': float(request.form.get('venue_lat', 0.0)),
                'lng': float(request.form.get('venue_lng', 0.0))
            }
            
            # Process ticket fields configuration
            ticket_fields = {
                'name': {
                    'enabled': bool(request.form.get('ticket_fields[name][enabled]')),
                    'required': bool(request.form.get('ticket_fields[name][required]'))
                },
                'email': {
                    'enabled': bool(request.form.get('ticket_fields[email][enabled]')),
                    'required': bool(request.form.get('ticket_fields[email][required]'))
                },
                'phone': {
                    'enabled': bool(request.form.get('ticket_fields[phone][enabled]')),
                    'required': bool(request.form.get('ticket_fields[phone][required]'))
                },
                'age': {
                    'enabled': bool(request.form.get('ticket_fields[age][enabled]')),
                    'required': bool(request.form.get('ticket_fields[age][required]'))
                },
                'gender': {
                    'enabled': bool(request.form.get('ticket_fields[gender][enabled]')),
                    'required': bool(request.form.get('ticket_fields[gender][required]'))
                },
                'id_proof': {
                    'enabled': bool(request.form.get('ticket_fields[id_proof][enabled]')),
                    'required': bool(request.form.get('ticket_fields[id_proof][required]'))
                },
                'address': {
                    'enabled': bool(request.form.get('ticket_fields[address][enabled]')),
                    'required': bool(request.form.get('ticket_fields[address][required]'))
                },
                'custom_fields': []  # Add support for custom fields if needed
            }
            
            # Ensure at least name and email are enabled
            if not ticket_fields['name']['enabled'] or not ticket_fields['email']['enabled']:
                flash('Name and email fields must be enabled')
                return redirect(url_for('new_event'))
            
            # Create the event with the appropriate status based on action
            event = Event(
                host_id=current_user.id,
                name=request.form.get('name'),
                description=request.form.get('description'),
                event_type=request.form.get('event_type'),
                start_date=datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M'),
                end_date=datetime.strptime(request.form.get('end_date'), '%Y-%m-%dT%H:%M'),
                venue=request.form.get('venue'),
                venue_address=request.form.get('venue_address'),
                venue_coordinates=venue_coordinates,
                total_seats=total_seats,
                available_seats=total_seats,
                price_tiers=price_tiers,
                status='published' if action == 'publish' else 'draft',
                is_featured=bool(request.form.get('is_featured')),
                allow_refunds=bool(request.form.get('allow_refunds')),
                show_remaining_tickets=bool(request.form.get('show_remaining_tickets')),
                enable_waitlist=bool(request.form.get('enable_waitlist')),
                booking_deadline=int(request.form.get('booking_deadline', 0)),
                ticket_limit=int(request.form.get('ticket_limit', 0)),
                ticket_fields=ticket_fields
            )
            
            # Handle file uploads
            if 'featured_image' in request.files:
                file = request.files['featured_image']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    event.featured_image = filename
            
            db.session.add(event)
            db.session.commit()
            
            flash(f'Event {action}ed successfully!')
            return redirect(url_for('host_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating event: {str(e)}')
            return redirect(url_for('new_event'))
            
    # Create a dummy event with default values
    dummy_event = Event(
        host_id=current_user.id,
        name='',
        description='',
        event_type='',
        start_date=datetime.now(),
        end_date=datetime.now(),
        venue='',
        venue_address='',
        venue_coordinates={'lat': 0.0, 'lng': 0.0},
        total_seats=0,
        available_seats=0,
        price_tiers=[],
        status='draft',
        ticket_fields={
            'name': {'required': True, 'enabled': True},
            'email': {'required': True, 'enabled': True},
            'phone': {'required': False, 'enabled': True},
            'age': {'required': False, 'enabled': False},
            'gender': {'required': False, 'enabled': False},
            'id_proof': {'required': False, 'enabled': False},
            'address': {'required': False, 'enabled': False},
            'custom_fields': []
        }
    )
    
    return render_template('events/event_form.html', form=form, event=dummy_event)

@app.route('/host/events/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@host_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    # Ensure the current user is the event host
    if event.host_id != current_user.id:
        flash('You do not have permission to edit this event.')
        return redirect(url_for('host_events'))
        
    if request.method == 'POST':
        try:
            # Get the action (publish or draft)
            action = request.form.get('action', 'draft')
            
            # Update event details
            event.name = request.form.get('name')
            event.description = request.form.get('description')
            event.event_type = request.form.get('event_type')
            event.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
            event.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%dT%H:%M')
            event.venue = request.form.get('venue')
            event.venue_address = request.form.get('venue_address')
            event.venue_coordinates = {
                'lat': float(request.form.get('venue_lat', 0.0)),
                'lng': float(request.form.get('venue_lng', 0.0))
            }
            
            # Process ticket tiers
            tier_names = request.form.getlist('tier_names[]')
            tier_prices = request.form.getlist('tier_prices[]')
            tier_quantities = request.form.getlist('tier_quantities[]')
            
            if not tier_names or not tier_prices or not tier_quantities:
                flash('At least one price tier is required')
                return redirect(url_for('edit_event', event_id=event_id))
            
            # Validate ticket quantities
            total_seats = int(request.form.get('total_seats', 0))
            total_tier_quantities = sum(int(qty) for qty in tier_quantities)
            
            if total_tier_quantities > total_seats:
                flash('Sum of tier quantities cannot exceed total seats')
                return redirect(url_for('edit_event', event_id=event_id))
            
            # Update price tiers
            price_tiers = []
            for i in range(len(tier_names)):
                try:
                    price = float(tier_prices[i])
                    quantity = int(tier_quantities[i])
                    if price <= 0:
                        flash('Price must be greater than 0')
                        return redirect(url_for('edit_event', event_id=event_id))
                    if quantity <= 0:
                        flash('Quantity must be greater than 0')
                        return redirect(url_for('edit_event', event_id=event_id))
                except ValueError:
                    flash('Invalid price or quantity value')
                    return redirect(url_for('edit_event', event_id=event_id))
                    
                price_tiers.append({
                    'id': f'tier_{i+1}',
                    'name': tier_names[i],
                    'price': price,
                    'quantity': quantity
                })
            
            # Update event with new values
            event.total_seats = total_seats
            event.available_seats = total_seats
            event.price_tiers = price_tiers
            event.status = 'published' if action == 'publish' else 'draft'
            
            # Update settings
            event.is_featured = bool(request.form.get('is_featured'))
            event.allow_refunds = bool(request.form.get('allow_refunds'))
            event.show_remaining_tickets = bool(request.form.get('show_remaining_tickets'))
            event.enable_waitlist = bool(request.form.get('enable_waitlist'))
            event.booking_deadline = int(request.form.get('booking_deadline', 0))
            event.ticket_limit = int(request.form.get('ticket_limit', 0))
            
            # Handle file uploads
            if 'featured_image' in request.files:
                file = request.files['featured_image']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    event.featured_image = filename
            
            # Process ticket fields configuration
            ticket_fields = {
                'name': {
                    'enabled': bool(request.form.get('ticket_fields[name][enabled]')),
                    'required': bool(request.form.get('ticket_fields[name][required]'))
                },
                'email': {
                    'enabled': bool(request.form.get('ticket_fields[email][enabled]')),
                    'required': bool(request.form.get('ticket_fields[email][required]'))
                },
                'phone': {
                    'enabled': bool(request.form.get('ticket_fields[phone][enabled]')),
                    'required': bool(request.form.get('ticket_fields[phone][required]'))
                },
                'age': {
                    'enabled': bool(request.form.get('ticket_fields[age][enabled]')),
                    'required': bool(request.form.get('ticket_fields[age][required]'))
                },
                'gender': {
                    'enabled': bool(request.form.get('ticket_fields[gender][enabled]')),
                    'required': bool(request.form.get('ticket_fields[gender][required]'))
                },
                'id_proof': {
                    'enabled': bool(request.form.get('ticket_fields[id_proof][enabled]')),
                    'required': bool(request.form.get('ticket_fields[id_proof][required]'))
                },
                'address': {
                    'enabled': bool(request.form.get('ticket_fields[address][enabled]')),
                    'required': bool(request.form.get('ticket_fields[address][required]'))
                },
                'custom_fields': []  # Add support for custom fields if needed
            }
            
            # Ensure at least name and email are enabled
            if not ticket_fields['name']['enabled'] or not ticket_fields['email']['enabled']:
                flash('Name and email fields must be enabled')
                return redirect(url_for('edit_event', event_id=event_id))
            
            # Update event with new ticket fields
            event.ticket_fields = ticket_fields
            
            db.session.commit()
            flash(f'Event {action}ed successfully!')
            return redirect(url_for('host_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating event: {str(e)}')
            
    return render_template('events/event_form.html', event=event)

@app.route('/host/events/<int:event_id>/sub-events/new', methods=['GET', 'POST'])
@login_required
@host_required
def new_sub_event(event_id):
    parent_event = Event.query.get_or_404(event_id)
    
    # Ensure the current user is the event host
    if parent_event.host_id != current_user.id:
        flash('You do not have permission to add sub-events.')
        return redirect(url_for('host_events'))
        
    if request.method == 'POST':
        try:
            price_tiers = json.loads(request.form.get('price_tiers'))
            
            sub_event = Event(
                host_id=current_user.id,
                parent_id=parent_event.id,
                name=request.form.get('name'),
                description=request.form.get('description'),
                event_type=parent_event.event_type,
                start_date=datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M'),
                end_date=datetime.strptime(request.form.get('end_date'), '%Y-%m-%dT%H:%M'),
                venue=parent_event.venue,
                venue_address=parent_event.venue_address,
                venue_coordinates=parent_event.venue_coordinates,
                total_seats=int(request.form.get('total_seats')),
                available_seats=int(request.form.get('total_seats')),
                price_tiers=price_tiers,
                status='draft'
            )
            
            db.session.add(sub_event)
            db.session.commit()
            
            flash('Sub-event created successfully!')
            return redirect(url_for('edit_event', event_id=parent_event.id))
            
        except Exception as e:
            flash(f'Error creating sub-event: {str(e)}')
            
    return render_template('events/event_form.html', parent_event=parent_event)

@app.route('/host/events/<int:event_id>/publish', methods=['POST'])
@login_required
@host_required
def publish_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    if event.host_id != current_user.id:
        flash('You do not have permission to publish this event.')
        return redirect(url_for('host_events'))
        
    event.status = 'published'
    db.session.commit()
    
    flash('Event published successfully!')
    return redirect(url_for('edit_event', event_id=event.id))

@app.route('/host/events/<int:event_id>/cancel', methods=['POST'])
@login_required
@host_required
def cancel_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    if event.host_id != current_user.id:
        flash('You do not have permission to cancel this event.')
        return redirect(url_for('host_events'))
        
    try:
        # Start transaction
        event.status = 'cancelled'
        event.cancelled_at = datetime.utcnow()
        
        # Notify all ticket holders about cancellation
        for booking in event.bookings:
            if booking.status == 'completed':
                # TODO: Implement notification system
                # TODO: Handle refunds through payment gateway
                booking.status = 'refunded'
                booking.refunded_at = datetime.utcnow()
        
        db.session.commit()
        flash('Event cancelled successfully. All ticket holders will be notified.')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling event: {str(e)}')
        
    return redirect(url_for('host_dashboard'))

@app.route('/host/events/<int:event_id>/bookings')
@login_required
@host_required
def event_bookings(event_id):
    # Get event with bookings relationship eagerly loaded
    event = Event.query.options(db.joinedload(Event.bookings)).get_or_404(event_id)
    
    if event.host_id != current_user.id:
        flash('You do not have permission to view these bookings.')
        return redirect(url_for('host_events'))
    
    # Get bookings sorted by date
    bookings = sorted(event.bookings, key=lambda x: x.booking_date, reverse=True)
    
    # Calculate statistics
    stats = {
        'total_tickets': sum(b.num_tickets for b in bookings),
        'total_revenue': sum(b.total_price for b in bookings if b.status == 'completed'),
        'checked_in': sum(1 for b in bookings if b.check_in_status),
        'refunded': sum(1 for b in bookings if b.status == 'refunded')
    }
    
    return render_template('events/event_bookings.html', event=event, bookings=bookings, stats=stats)

@app.route('/process-payment/<booking_type>/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def process_payment(booking_type, booking_id):
    print(f"DEBUG: Payment route hit for booking_type={booking_type}, booking_id={booking_id}")
    try:
        if booking_type == 'flight':
            booking = FlightBooking.query.get_or_404(booking_id)
            amount = booking.total_fare
        elif booking_type == 'train':
            booking = TrainBooking.query.get_or_404(booking_id)
            amount = booking.total_fare
        else:
            booking = Booking.query.get_or_404(booking_id)
            amount = booking.total_price
        
        print(f"DEBUG: Found booking with amount={amount}")
        
        if booking.user_id != current_user.id:
            flash('Unauthorized access', 'error')
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            print("DEBUG: Processing POST request")
            try:
                # Get payment details from form
                payment_id = request.form.get('razorpay_payment_id')
                order_id = request.form.get('razorpay_order_id')
                signature = request.form.get('razorpay_signature')
                
                print(f"DEBUG: Payment details received - payment_id={payment_id}, order_id={order_id}")
                
                if not payment_id or not order_id or not signature:
                    flash('Missing payment details', 'error')
                    return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
                
                # Verify the payment signature
                params_dict = {
                    'razorpay_payment_id': payment_id,
                    'razorpay_order_id': order_id,
                    'razorpay_signature': signature
                }
                
                # Verify signature
                razorpay_client.utility.verify_payment_signature(params_dict)
                
                # Verify payment status
                payment = razorpay_client.payment.fetch(payment_id)
                if payment['status'] != 'captured':
                    flash('Payment not completed', 'error')
                    return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
                
                # Update booking status
                booking.payment_status = 'completed'
                booking.payment_id = payment_id
                booking.status = 'confirmed'  # Update booking status
                db.session.commit()
                
                flash('Payment processed successfully!', 'success')
                
                if booking_type == 'flight':
                    return redirect(url_for('my_flight_bookings'))
                elif booking_type == 'train':
                    return redirect(url_for('my_train_bookings'))
                else:
                    return redirect(url_for('my_bookings'))
                    
            except razorpay.errors.SignatureVerificationError:
                db.session.rollback()
                flash('Payment verification failed: Invalid signature', 'error')
                return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
            except razorpay.errors.RazorpayError as e:
                db.session.rollback()
                flash(f'Payment processing failed: {str(e)}', 'error')
                return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'error')
                return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
        
        try:
            # Check if there's an existing order for this booking
            if booking.payment_id:
                flash('This booking has already been paid for', 'error')
                return redirect(url_for('my_bookings'))
            
            # Create Razorpay Order
            amount_in_paise = int(amount * 100)  # Convert to paise
            order_data = {
                'amount': amount_in_paise,
                'currency': 'INR',
                'payment_capture': 1,
                'notes': {
                    'booking_type': booking_type,
                    'booking_id': str(booking_id)
                }
            }
            print(f"DEBUG: Creating Razorpay order with data: {order_data}")
            order = razorpay_client.order.create(order_data)
            print(f"DEBUG: Razorpay order created: {order}")
            
            return render_template(
                'payment/process.html',
                booking=booking,
                booking_type=booking_type,
                razorpay_order_id=order['id'],
                razorpay_key_id=os.getenv('RAZORPAY_KEY_ID'),
                amount=amount,
                currency='INR'
            )
        except razorpay.errors.RazorpayError as e:
            flash(f'Error creating payment order: {str(e)}', 'error')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            return redirect(url_for('index'))
            
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/api/bookings/<int:booking_id>')
@login_required
def get_booking_details(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.event.host_id != current_user.id:
        return jsonify({'error': 'Unauthorized access'}), 403
    
    return jsonify({
        'id': booking.id,
        'user': {
            'name': booking.user.name if booking.user else 'Unknown User',
            'email': booking.user.email if booking.user else 'No email',
            'phone': booking.user.phone if booking.user else None
        },
        'ticket_tier': booking.ticket_tier,
        'quantity': booking.num_tickets,
        'total_amount': booking.total_price,
        'created_at': booking.created_at.isoformat() if booking.created_at else None,
        'check_in_status': booking.check_in_status,
        'checked_in_at': booking.checked_in_at.isoformat() if booking.checked_in_at else None,
        'status': booking.status,
        'refunded_at': booking.refunded_at.isoformat() if booking.refunded_at else None
    })

@app.route('/api/bookings/<int:booking_id>/check-in', methods=['POST'])
@login_required
def check_in_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.event.host_id != current_user.id:
        return jsonify({'error': 'Unauthorized access'}), 403
    
    if booking.check_in_status:
        return jsonify({'error': 'Booking already checked in'}), 400
    
    if booking.status == 'refunded':
        return jsonify({'error': 'Cannot check in refunded booking'}), 400
    
    booking.check_in_status = True
    booking.checked_in_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/bookings/<int:booking_id>/refund', methods=['POST'])
@login_required
def refund_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.event.host_id != current_user.id:
        return jsonify({'error': 'Unauthorized access'}), 403
    
    if booking.status == 'refunded':
        return jsonify({'error': 'Booking already refunded'}), 400
    
    if booking.check_in_status:
        return jsonify({'error': 'Cannot refund checked-in booking'}), 400
    
    # Process refund through payment gateway
    try:
        razorpay_client.payment.refund(booking.payment_id)
        booking.status = 'refunded'
        booking.refunded_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/<int:event_id>/bookings/export')
@login_required
def export_event_bookings(event_id):
    event = Event.query.get_or_404(event_id)
    if event.host_id != current_user.id:
        return jsonify({'error': 'Unauthorized access'}), 403
    
    # Create CSV data
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Booking ID', 'Customer Name', 'Email', 'Ticket Type', 'Quantity', 'Total Amount', 'Status', 'Booked On'])
    
    for booking in event.bookings:
        writer.writerow([
            booking.id,
            booking.user.name if booking.user else 'Unknown User',
            booking.user.email if booking.user else 'No email',
            booking.ticket_tier.get('name', 'Standard') if booking.ticket_tier else 'Standard',
            booking.num_tickets,
            booking.total_price,
            'Checked In' if booking.check_in_status else 'Refunded' if booking.status == 'refunded' else 'Confirmed',
            booking.created_at.strftime('%Y-%m-%d %H:%M:%S') if booking.created_at else 'N/A'
        ])
    
    # Create response
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=bookings_{event_id}_{datetime.now().strftime("%Y%m%d")}.csv'}
    )

@app.route('/ticket/<int:booking_id>')
@login_required
def ticket(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        abort(403)
    share_url = url_for('public_ticket', share_id=booking.share_id, _external=True)
    return render_template('tickets/ticket.html', booking=booking, share_url=share_url)

@app.route('/ticket/share/<share_id>')
def public_ticket(share_id):
    booking = Booking.query.filter_by(share_id=share_id).first_or_404()
    return render_template('tickets/ticket.html', booking=booking, is_public=True)

@app.route('/wallet')
@login_required
def wallet():
    # Create wallet if it doesn't exist
    if not current_user.wallet:
        wallet = Wallet(user_id=current_user.id)
        db.session.add(wallet)
        db.session.commit()
    
    # Query transactions directly instead of using relationship property
    transactions = Transaction.query.filter_by(wallet_id=current_user.wallet.id).order_by(Transaction.created_at.desc()).limit(10).all()
    return render_template('wallet/index.html', wallet=current_user.wallet, transactions=transactions)

@app.route('/wallet/add', methods=['GET', 'POST'])
@login_required
def add_money():
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount', 0))
            if amount <= 0:
                flash('Please enter a valid amount')
                return redirect(url_for('add_money'))
            
            # Initialize Razorpay client
            client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID'), os.getenv('RAZORPAY_KEY_SECRET')))
            
            # Create Razorpay order
            order_amount = int(amount * 100)  # Convert to paise
            order_currency = 'INR'
            order_receipt = f'wallet_topup_{current_user.id}_{int(datetime.utcnow().timestamp())}'
            
            order = client.order.create({
                'amount': order_amount,
                'currency': order_currency,
                'receipt': order_receipt,
                'payment_capture': 1
            })
            
            return render_template(
                'wallet/payment.html',
                order_id=order['id'],
                amount=amount,
                key_id=os.getenv('RAZORPAY_KEY_ID')
            )
            
        except ValueError:
            flash('Please enter a valid amount')
            return redirect(url_for('add_money'))
    
    return render_template('wallet/add_money.html')

@app.route('/wallet/add/success', methods=['POST'])
@login_required
def payment_success():
    try:
        # Verify payment signature
        client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID'), os.getenv('RAZORPAY_KEY_SECRET')))
        
        payment_id = request.form.get('razorpay_payment_id')
        order_id = request.form.get('razorpay_order_id')
        signature = request.form.get('razorpay_signature')
        
        client.utility.verify_payment_signature({
            'razorpay_payment_id': payment_id,
            'razorpay_order_id': order_id,
            'razorpay_signature': signature
        })
        
        # Get payment details
        payment = client.payment.fetch(payment_id)
        amount = float(payment['amount']) / 100  # Convert from paise to rupees
        
        # Add money to wallet
        current_user.wallet.add_money(
            amount=amount,
            transaction_type='deposit',
            reference_id=payment_id,
            description=f'Added ₹{amount} via Razorpay'
        )
        
        flash('Money added to wallet successfully!')
        return redirect(url_for('wallet'))
        
    except Exception as e:
        flash('Payment verification failed')
        return redirect(url_for('wallet'))

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_sample_stations()  # Initialize sample stations
        init_sample_airports()  # Initialize sample airports
    app.run(debug=True) 