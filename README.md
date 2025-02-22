# Ticket Booking System

A Flask-based web application for booking tickets to various events like movies, concerts, and sports events.

## Features

- User registration and authentication
- Browse upcoming events
- View event details
- Book tickets for events
- View booking history
- Responsive design using Bootstrap

## Prerequisites

- Python 3.8 or higher
- PostgreSQL database
- pip (Python package manager)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ticket-infra-python
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the required packages:
```bash
pip install -r requirements.txt
```

4. Create a PostgreSQL database named `ticket_booking`

5. Configure the environment variables:
   - Copy the `.env.example` file to `.env`
   - Update the database URL and secret key in the `.env` file

6. Initialize the database:
```bash
flask db init
flask db migrate
flask db upgrade
```

## Running the Application

1. Make sure your virtual environment is activated

2. Start the Flask development server:
```bash
python app.py
```

3. Open your web browser and navigate to `http://localhost:5000`

## Database Schema

The application uses the following database models:

- User: Stores user information and authentication details
- Event: Stores event information including name, description, venue, and available seats
- Booking: Stores booking information linking users and events

## Contributing

1. Fork the repository
2. Create a new branch for your feature
3. Commit your changes
4. Push to your branch
5. Create a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details. # Tickety
