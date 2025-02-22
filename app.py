from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from models import db, User, Event, Booking, Train, TrainBooking, Station, Flight, FlightBooking, Airport, Airline
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
            
            # Validate attendee details
            if not attendee_details['name'] or not attendee_details['email']:
                flash('Name and email are required')
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
                    tier_name=selected_tier['name'],  # Store the tier name
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
    events = Event.query.filter_by(host_id=current_user.id).order_by(Event.created_at.desc()).all()
    active_events = [e for e in events if e.status == 'published' and e.end_date > datetime.utcnow()]
    
    stats = {
        'total_events': len(events),
        'active_events': len(active_events),
        'published_events': len([e for e in events if e.status == 'published']),
        'total_tickets': sum(len(e.bookings) for e in events),
        'total_capacity': sum(e.total_seats for e in events),
        'total_bookings': sum(len(e.bookings) for e in events),
        'total_revenue': sum(b.total_price for e in events for b in e.bookings)
    }
    return render_template('events/host_dashboard.html', events=events, stats=stats)

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
                ticket_limit=int(request.form.get('ticket_limit', 0))
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
            
    return render_template('events/event_form.html', form=form)

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
        
    event.status = 'cancelled'
    db.session.commit()
    
    # Notify all ticket holders
    for booking in event.bookings:
        # TODO: Implement notification system
        pass
    
    flash('Event cancelled successfully!')
    return redirect(url_for('edit_event', event_id=event.id))

@app.route('/host/events/<int:event_id>/bookings')
@login_required
@host_required
def event_bookings(event_id):
    event = Event.query.get_or_404(event_id)
    
    if event.host_id != current_user.id:
        flash('You do not have permission to view these bookings.')
        return redirect(url_for('host_events'))
        
    bookings = Booking.query.filter_by(event_id=event.id).order_by(Booking.booking_date.desc()).all()
    return render_template('events/event_bookings.html', event=event, bookings=bookings)

@app.route('/process-payment/<booking_type>/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def process_payment(booking_type, booking_id):
    if booking_type == 'flight':
        booking = FlightBooking.query.get_or_404(booking_id)
        amount = booking.total_fare
    elif booking_type == 'train':
        booking = TrainBooking.query.get_or_404(booking_id)
        amount = booking.total_fare
    else:
        booking = Booking.query.get_or_404(booking_id)
        amount = booking.total_price
    
    if booking.user_id != current_user.id:
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            # Verify the payment signature
            params_dict = {
                'razorpay_payment_id': request.form.get('razorpay_payment_id'),
                'razorpay_order_id': request.form.get('razorpay_order_id'),
                'razorpay_signature': request.form.get('razorpay_signature')
            }
            
            # Verify signature
            razorpay_client.utility.verify_payment_signature(params_dict)
            
            # Update booking status
            booking.payment_status = 'completed'
            booking.payment_id = request.form.get('razorpay_payment_id')
            db.session.commit()
            
            flash('Payment processed successfully!', 'success')
            
            if booking_type == 'flight':
                return redirect(url_for('my_flight_bookings'))
            elif booking_type == 'train':
                return redirect(url_for('my_train_bookings'))
            else:
                return redirect(url_for('my_bookings'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Payment verification failed: {str(e)}', 'error')
            return redirect(url_for('process_payment', booking_type=booking_type, booking_id=booking_id))
    
    try:
        # Create Razorpay Order
        amount_in_paise = int(amount * 100)  # Convert to paise
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'payment_capture': 1
        }
        order = razorpay_client.order.create(order_data)
        
        return render_template(
            'payment/process.html',
            booking=booking,
            booking_type=booking_type,
            razorpay_order_id=order['id'],
            razorpay_key_id=os.getenv('RAZORPAY_KEY_ID'),
            amount=amount,
            currency='INR'
        )
    except Exception as e:
        flash(f'Error creating payment order: {str(e)}', 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_sample_stations()  # Initialize sample stations
        init_sample_airports()  # Initialize sample airports
    app.run(debug=True) 