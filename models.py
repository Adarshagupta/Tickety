from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
import json
from io import BytesIO
from flask import url_for

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_host = db.Column(db.Boolean, default=False)
    host_info = db.Column(db.JSON, nullable=True)  # Store host details like organization, contact, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    bookings = db.relationship('Booking', back_populates='user', lazy=True)
    train_bookings = db.relationship('TrainBooking', back_populates='user', lazy=True)
    flight_bookings = db.relationship('FlightBooking', back_populates='user', lazy=True)
    hosted_events = db.relationship('Event', back_populates='host', lazy=True)
    wallet = db.relationship('Wallet', back_populates='user', uselist=False, lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), nullable=False, default='INR')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='wallet', lazy=True)
    transactions = db.relationship('Transaction', back_populates='wallet', lazy=True)

    def add_money(self, amount, transaction_type='deposit', reference_id=None, description=None):
        """Add money to wallet and create a transaction record."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
            
        self.balance += amount
        transaction = Transaction(
            wallet_id=self.id,
            amount=amount,
            type=transaction_type,
            reference_id=reference_id,
            description=description or f"Added ₹{amount} to wallet"
        )
        db.session.add(transaction)
        db.session.commit()
        return transaction

    def deduct_money(self, amount, transaction_type='payment', reference_id=None, description=None):
        """Deduct money from wallet and create a transaction record."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if amount > self.balance:
            raise ValueError("Insufficient balance")
            
        self.balance -= amount
        transaction = Transaction(
            wallet_id=self.id,
            amount=-amount,  # Negative amount for deductions
            type=transaction_type,
            reference_id=reference_id,
            description=description or f"Deducted ₹{amount} from wallet"
        )
        db.session.add(transaction)
        db.session.commit()
        return transaction

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)  # Positive for credit, negative for debit
    type = db.Column(db.String(20), nullable=False)  # deposit, payment, refund, withdrawal
    status = db.Column(db.String(20), nullable=False, default='completed')
    reference_id = db.Column(db.String(100), nullable=True)  # For linking to bookings, etc.
    description = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    wallet = db.relationship('Wallet', back_populates='transactions', lazy=True)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)  # For sub-events
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(250), unique=True, nullable=False)
    description = db.Column(db.Text)
    event_type = db.Column(db.String(50), nullable=False)  # movie, concert, sports, etc.
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    venue = db.Column(db.String(200), nullable=False)
    venue_address = db.Column(db.Text, nullable=True)
    venue_coordinates = db.Column(db.JSON, nullable=True)  # {lat: xx, lng: xx}
    total_seats = db.Column(db.Integer, nullable=False)
    available_seats = db.Column(db.Integer, nullable=False)
    price_tiers = db.Column(db.JSON, nullable=False)  # List of price tiers with details
    status = db.Column(db.String(20), default='draft')  # draft, published, private, cancelled, completed
    featured_image = db.Column(db.String(500), nullable=True)
    gallery_images = db.Column(db.JSON, nullable=True)  # List of image URLs
    custom_fields = db.Column(db.JSON, nullable=True)  # For additional event-specific fields
    meta_tags = db.Column(db.JSON, nullable=True)  # For SEO
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # New settings fields
    is_featured = db.Column(db.Boolean, default=False)
    allow_refunds = db.Column(db.Boolean, default=True)
    show_remaining_tickets = db.Column(db.Boolean, default=True)
    enable_waitlist = db.Column(db.Boolean, default=False)
    booking_deadline = db.Column(db.Integer, default=0)  # Hours before event start
    ticket_limit = db.Column(db.Integer, default=0)  # 0 means no limit
    
    # New fields for ticket personalization
    ticket_fields = db.Column(db.JSON, nullable=False, default=lambda: {
        'name': {'required': True, 'enabled': True},
        'email': {'required': True, 'enabled': True},
        'phone': {'required': False, 'enabled': True},
        'age': {'required': False, 'enabled': False},
        'gender': {'required': False, 'enabled': False},
        'id_proof': {'required': False, 'enabled': False},
        'address': {'required': False, 'enabled': False},
        'custom_fields': []
    })
    ticket_instructions = db.Column(db.Text, nullable=True)
    ticket_template = db.Column(db.String(50), default='default')
    show_qr_code = db.Column(db.Boolean, default=True)
    show_barcode = db.Column(db.Boolean, default=True)
    
    # Relationships
    host = db.relationship('User', back_populates='hosted_events', lazy=True)
    bookings = db.relationship('Booking', back_populates='event', lazy=True)
    sub_events = db.relationship('Event', backref=db.backref('parent', remote_side=[id]), lazy=True)

    def __init__(self, *args, **kwargs):
        super(Event, self).__init__(*args, **kwargs)
        if not self.slug:
            self.slug = self.generate_slug()

    def generate_slug(self):
        base_slug = "-".join(w.lower() for w in self.name.split())
        suffix = ""
        counter = 1
        while True:
            slug = base_slug + suffix
            if not Event.query.filter_by(slug=slug).first():
                return slug
            suffix = f"-{counter}"
            counter += 1

    def get_featured_image_url(self):
        """Get the full URL for the featured image."""
        if not self.featured_image:
            return None
        return url_for('static', filename=f'uploads/{self.featured_image}')

    def to_dict(self):
        """Convert event object to dictionary."""
        return {
            'id': self.id,
            'host_id': self.host_id,
            'parent_id': self.parent_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'event_type': self.event_type,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'venue': self.venue,
            'venue_address': self.venue_address,
            'venue_coordinates': self.venue_coordinates,
            'total_seats': self.total_seats,
            'available_seats': self.available_seats,
            'price_tiers': self.price_tiers,
            'status': self.status,
            'featured_image': self.get_featured_image_url(),
            'gallery_images': self.gallery_images,
            'custom_fields': self.custom_fields,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Booking(db.Model):
    __tablename__ = 'booking'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    num_tickets = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    tier_id = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, completed, cancelled, refunded
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    payment_id = db.Column(db.String(100), nullable=True)
    attendee_details = db.Column(db.JSON, nullable=True)
    check_in_status = db.Column(db.Boolean, default=False)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)
    ticket_code = db.Column(db.String(20), nullable=True)
    qr_code = db.Column(db.Text, nullable=True)
    barcode = db.Column(db.Text, nullable=True)
    
    # Relationships
    user = db.relationship('User', back_populates='bookings', lazy=True)
    event = db.relationship('Event', back_populates='bookings', lazy=True)
    
    @property
    def ticket_tier(self):
        """Get the ticket tier information."""
        if not self.event or not self.event.price_tiers or not self.tier_id:
            return {'name': 'Standard', 'price': self.total_price / self.num_tickets}
        
        # Handle both list and dictionary cases
        tiers = self.event.price_tiers
        if isinstance(tiers, list):
            # If tiers is a list, find matching tier by id
            for tier in tiers:
                if isinstance(tier, dict) and str(tier.get('id', '')) == str(self.tier_id):
                    return tier
        elif isinstance(tiers, dict):
            # If tiers is a dictionary, use get method
            return tiers.get(str(self.tier_id), {'name': 'Standard', 'price': self.total_price / self.num_tickets})
        
        # Return default if no match found
        return {'name': 'Standard', 'price': self.total_price / self.num_tickets}
    
    def generate_ticket_code(self):
        """Generate a unique ticket code."""
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        while Booking.query.filter_by(ticket_code=code).first():
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return code
    
    def generate_qr_code(self):
        """Generate QR code for the ticket."""
        from utils.ticket_utils import generate_qr_code
        data = {
            'booking_id': self.id,
            'event_id': self.event_id,
            'ticket_code': self.ticket_code,
            'attendee': self.attendee_details.get('name') if isinstance(self.attendee_details, dict) else None
        }
        return generate_qr_code(json.dumps(data))
    
    def generate_barcode(self):
        """Generate barcode for the ticket."""
        from utils.ticket_utils import generate_barcode
        return generate_barcode(self.ticket_code)

class Train(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    train_number = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # Express, Superfast, etc.
    from_station = db.Column(db.JSON, nullable=False)  # Station details
    to_station = db.Column(db.JSON, nullable=False)  # Station details
    departure_time = db.Column(db.DateTime, nullable=False)
    arrival_time = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.String(50), nullable=False)
    distance = db.Column(db.Integer, nullable=False)  # in kilometers
    days = db.Column(db.JSON, nullable=False)  # Running days
    classes = db.Column(db.JSON, nullable=False)  # Available classes
    pantry = db.Column(db.Boolean, default=False)
    wifi = db.Column(db.Boolean, default=False)
    route = db.Column(db.JSON, nullable=False)  # List of stations in route
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TrainBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    train_number = db.Column(db.String(10), nullable=False)
    pnr = db.Column(db.String(10), unique=True, nullable=False)
    travel_class = db.Column(db.String(5), nullable=False)  # 1A, 2A, 3A, SL, etc.
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    journey_date = db.Column(db.DateTime, nullable=False)
    num_passengers = db.Column(db.Integer, nullable=False)
    total_fare = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='confirmed')  # confirmed, cancelled, waitlisted
    passengers = db.Column(db.JSON, nullable=False)  # List of passenger details
    seat_numbers = db.Column(db.JSON, nullable=True)  # Assigned seat numbers
    contact_email = db.Column(db.String(120), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    payment_id = db.Column(db.String(100), nullable=True)
    payment_status = db.Column(db.String(20), default='pending')
    cancellation_time = db.Column(db.DateTime, nullable=True)
    refund_status = db.Column(db.String(20), nullable=True)
    refund_amount = db.Column(db.Float, nullable=True)

    # Relationships
    user = db.relationship('User', back_populates='train_bookings', lazy=True)

class Station(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    zone = db.Column(db.String(50), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

class Airport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(3), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    timezone = db.Column(db.String(50), nullable=True)
    departures = db.relationship('Flight', foreign_keys='Flight.origin_airport_id', back_populates='origin_airport')
    arrivals = db.relationship('Flight', foreign_keys='Flight.destination_airport_id', back_populates='destination_airport')

class Airline(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(2), unique=True, nullable=False)  # IATA code
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    flights = db.relationship('Flight', back_populates='airline')

class Flight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flight_number = db.Column(db.String(10), unique=True, nullable=False)
    airline_id = db.Column(db.Integer, db.ForeignKey('airline.id'), nullable=False)
    origin_airport_id = db.Column(db.Integer, db.ForeignKey('airport.id'), nullable=False)
    destination_airport_id = db.Column(db.Integer, db.ForeignKey('airport.id'), nullable=False)
    departure_time = db.Column(db.DateTime, nullable=False)
    arrival_time = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.String(50), nullable=False)
    aircraft_type = db.Column(db.String(50), nullable=True)
    cabin_classes = db.Column(db.JSON, nullable=False)
    baggage_allowance = db.Column(db.JSON, nullable=False)
    amenities = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), default='scheduled')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Updated relationships
    airline = db.relationship('Airline', back_populates='flights')
    origin_airport = db.relationship('Airport', foreign_keys=[origin_airport_id], back_populates='departures')
    destination_airport = db.relationship('Airport', foreign_keys=[destination_airport_id], back_populates='arrivals')
    bookings = db.relationship('FlightBooking', back_populates='flight')

    def to_dict(self):
        """Convert flight object to dictionary."""
        return {
            'id': self.id,
            'flight_number': self.flight_number,
            'airline': {
                'code': self.airline.code,
                'name': self.airline.name,
                'logo_url': self.airline.logo_url
            },
            'origin': {
                'code': self.origin_airport.code,
                'name': self.origin_airport.name,
                'city': self.origin_airport.city,
                'terminal': None,  # Add terminal info if available
                'time': self.departure_time.isoformat()
            },
            'destination': {
                'code': self.destination_airport.code,
                'name': self.destination_airport.name,
                'city': self.destination_airport.city,
                'terminal': None,  # Add terminal info if available
                'time': self.arrival_time.isoformat()
            },
            'duration': self.duration,
            'aircraft_type': self.aircraft_type,
            'cabin_classes': self.cabin_classes,
            'baggage_allowance': self.baggage_allowance,
            'amenities': self.amenities,
            'status': self.status
        }

class FlightBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey('flight.id'), nullable=False)
    flight_number = db.Column(db.String(10), nullable=False)
    pnr = db.Column(db.String(6), unique=True, nullable=False)
    travel_class = db.Column(db.String(20), nullable=False)  # economy, business, first
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    journey_date = db.Column(db.DateTime, nullable=False)
    num_passengers = db.Column(db.Integer, nullable=False)
    total_fare = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='confirmed')  # confirmed, cancelled
    passengers = db.Column(db.JSON, nullable=False)  # List of passenger details
    seats = db.Column(db.JSON, nullable=True)  # Assigned seat numbers
    meal_preferences = db.Column(db.JSON, nullable=True)  # Meal choices
    special_requests = db.Column(db.JSON, nullable=True)  # Special assistance, etc.
    contact_email = db.Column(db.String(120), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    payment_id = db.Column(db.String(100), nullable=True)
    payment_status = db.Column(db.String(20), default='pending')
    cancellation_time = db.Column(db.DateTime, nullable=True)
    refund_status = db.Column(db.String(20), nullable=True)
    refund_amount = db.Column(db.Float, nullable=True)
    check_in_status = db.Column(db.Boolean, default=False)
    boarding_pass_url = db.Column(db.String(500), nullable=True)

    # Relationships
    user = db.relationship('User', back_populates='flight_bookings', lazy=True)
    flight = db.relationship('Flight', back_populates='bookings', lazy=True) 