import os
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

class FlightAPI:
    def __init__(self):
        self.api_key = os.getenv('AMADEUS_API_KEY')
        if not self.api_key:
            raise ValueError("AMADEUS_API_KEY environment variable is not set")
            
        self.api_secret = os.getenv('AMADEUS_API_SECRET')
        if not self.api_secret:
            raise ValueError("AMADEUS_API_SECRET environment variable is not set")
            
        self.base_url = os.getenv('AMADEUS_API_BASE_URL', 'https://test.api.amadeus.com')
        self._access_token = None
        self._token_expiry = None
        
    def _get_access_token(self) -> str:
        """Get OAuth2 access token from Amadeus API."""
        if self._is_token_valid():
            return self._access_token
            
        try:
            response = requests.post(
                f"{self.base_url}/v1/security/oauth2/token",
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.api_key,
                    'client_secret': self.api_secret
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data['access_token']
            self._token_expiry = datetime.now().timestamp() + data['expires_in']
            return self._access_token
            
        except requests.exceptions.Timeout:
            raise Exception("Authentication request timed out")
        except requests.exceptions.ConnectionError:
            raise Exception("Could not connect to authentication service")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Authentication failed: {str(e)}")
            
    def _make_request(self, endpoint: str, method: str = 'GET', params: Dict = None) -> Dict:
        """Make an authenticated request to the Amadeus API."""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                if not self._is_token_valid():
                    self._refresh_access_token()
                    
                headers = {
                    'Authorization': f'Bearer {self._get_access_token()}',
                    'Content-Type': 'application/json'
                }
                
                url = f'{self.base_url}/v2{endpoint}'
                
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=30
                )
                
                if response.status_code == 401:
                    # Token expired, refresh and retry
                    self._refresh_access_token()
                    retry_count += 1
                    continue
                    
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                if retry_count < max_retries - 1:
                    retry_count += 1
                    continue
                raise Exception("Request timed out after multiple retries")
                
            except requests.exceptions.ConnectionError:
                if retry_count < max_retries - 1:
                    retry_count += 1
                    continue
                raise Exception("Could not connect to the flight service after multiple retries")
                
            except requests.exceptions.RequestException as e:
                error_msg = str(e)
                if response and response.json():
                    error_msg = response.json().get('errors', [{'detail': str(e)}])[0].get('detail')
                raise Exception(f"Flight API error: {error_msg}")
                
        raise Exception("Maximum retries exceeded")
    
    def search_flights(self, origin: str, destination: str, date: str) -> List[Dict]:
        """Search for flights using Amadeus Flight Offers Search API."""
        params = {
            'originLocationCode': origin,
            'destinationLocationCode': destination,
            'departureDate': date,
            'adults': 1,
            'nonStop': True,
            'max': 20
        }
        
        try:
            response = self._make_request('/shopping/flight-offers', params=params)
            flights = []
            
            for offer in response.get('data', []):
                itinerary = offer['itineraries'][0]
                segment = itinerary['segments'][0]
                
                flight = {
                    'id': offer['id'],
                    'flight_number': segment['carrierCode'] + segment['number'],
                    'airline': {
                        'code': segment['carrierCode'],
                        'name': self._get_airline_name(segment['carrierCode'])
                    },
                    'origin': {
                        'code': segment['departure']['iataCode'],
                        'terminal': segment['departure'].get('terminal'),
                        'time': segment['departure']['at']
                    },
                    'destination': {
                        'code': segment['arrival']['iataCode'],
                        'terminal': segment['arrival'].get('terminal'),
                        'time': segment['arrival']['at']
                    },
                    'duration': itinerary['duration'],
                    'cabin_class': offer['travelerPricings'][0]['fareDetailsBySegment'][0]['cabin'],
                    'price': {
                        'amount': float(offer['price']['total']),
                        'currency': offer['price']['currency']
                    },
                    'available_seats': offer['numberOfBookableSeats']
                }
                flights.append(flight)
                
            return flights
            
        except Exception as e:
            print(f"Error searching flights: {str(e)}")
            return []
    
    def get_flight_details(self, flight_id: str) -> Dict:
        """Get detailed flight information using Flight Offers Price API."""
        try:
            response = self._make_request(f'/shopping/flight-offers/{flight_id}')
            offer = response['data']
            
            # Format the response similar to search_flights
            itinerary = offer['itineraries'][0]
            segment = itinerary['segments'][0]
            
            return {
                'id': offer['id'],
                'flight_number': segment['carrierCode'] + segment['number'],
                'airline': {
                    'code': segment['carrierCode'],
                    'name': self._get_airline_name(segment['carrierCode'])
                },
                'origin': {
                    'code': segment['departure']['iataCode'],
                    'terminal': segment['departure'].get('terminal'),
                    'time': segment['departure']['at']
                },
                'destination': {
                    'code': segment['arrival']['iataCode'],
                    'terminal': segment['arrival'].get('terminal'),
                    'time': segment['arrival']['at']
                },
                'duration': itinerary['duration'],
                'cabin_class': offer['travelerPricings'][0]['fareDetailsBySegment'][0]['cabin'],
                'price': {
                    'amount': float(offer['price']['total']),
                    'currency': offer['price']['currency']
                },
                'available_seats': offer['numberOfBookableSeats'],
                'baggage_allowance': self._get_baggage_allowance(offer)
            }
            
        except Exception as e:
            print(f"Error getting flight details: {str(e)}")
            return {}
    
    def check_availability(self, flight_id: str, cabin_class: str = None) -> Dict:
        """Check flight availability and pricing."""
        try:
            response = self._make_request(f'/shopping/flight-offers/{flight_id}/pricing')
            offer = response['data']
            
            return {
                'available': offer['numberOfBookableSeats'] > 0,
                'seats': offer['numberOfBookableSeats'],
                'price': {
                    'amount': float(offer['price']['total']),
                    'currency': offer['price']['currency']
                },
                'fare_rules': self._get_fare_rules(offer)
            }
            
        except Exception as e:
            print(f"Error checking availability: {str(e)}")
            return {}
    
    def search_airports(self, query: str) -> List[Dict]:
        """Search for airports using Amadeus Airport & City Search API."""
        params = {
            'subType': 'AIRPORT',
            'keyword': query,
            'page[limit]': 10
        }
        
        try:
            response = self._make_request('/reference-data/locations', params=params)
            
            airports = []
            for data in response.get('data', []):
                airports.append({
                    'iata': data['iataCode'],
                    'name': data['name'],
                    'city': data['address'].get('cityName', ''),
                    'country': data['address'].get('countryName', ''),
                    'timezone': data.get('timeZoneOffset')
                })
                
            return airports
            
        except Exception as e:
            print(f"Error searching airports: {str(e)}")
            return []
    
    def _get_airline_name(self, carrier_code: str) -> str:
        """Get airline name from carrier code using Airline Code Lookup API."""
        try:
            response = self._make_request(f'/reference-data/airlines?airlineCodes={carrier_code}')
            return response['data'][0]['businessName']
        except Exception:
            return carrier_code  # Return carrier code if lookup fails
    
    def _get_baggage_allowance(self, offer: Dict) -> Dict:
        """Extract baggage allowance information from flight offer."""
        try:
            baggage = offer['travelerPricings'][0]['fareDetailsBySegment'][0].get('includedCheckedBags', {})
            return {
                'quantity': baggage.get('quantity', 0),
                'weight': baggage.get('weight'),
                'weightUnit': baggage.get('weightUnit')
            }
        except (KeyError, IndexError, TypeError):
            return {'quantity': 0}
    
    def _get_fare_rules(self, offer: Dict) -> Dict:
        """Extract fare rules from flight offer."""
        try:
            fare = offer['travelerPricings'][0]['fareDetailsBySegment'][0]
            return {
                'cabin': fare['cabin'],
                'fare_basis': fare.get('fareBasis'),
                'branded_fare': fare.get('brandedFare'),
                'class': fare.get('class')
            }
        except (KeyError, IndexError, TypeError):
            return {}

    def get_pnr_status(self, pnr: str) -> Dict:
        """Get booking status using PNR"""
        if not pnr or len(pnr) != 6:
            raise ValueError("Invalid PNR format")
            
        data = {'pnr': pnr}
        return self._make_request('/flights/pnr', data=data)

    def web_check_in(self, pnr: str, passengers: List[Dict]) -> Dict:
        """Perform web check-in"""
        if not pnr or len(pnr) != 6:
            raise ValueError("Invalid PNR format")
            
        if not passengers:
            raise ValueError("No passengers provided for check-in")
            
        data = {
            'pnr': pnr,
            'passengers': passengers
        }
        return self._make_request('/flights/checkin', data=data)

    def get_fare_rules(self, flight_number: str, travel_class: str) -> Dict:
        """Get fare rules and cancellation policy"""
        data = {
            'flightNumber': flight_number,
            'class': travel_class
        }
        response = self._make_request('/flights/fare-rules', data=data)
        return response

    def get_baggage_info(self, flight_number: str, travel_class: str) -> Dict:
        """Get baggage allowance information"""
        data = {
            'flightNumber': flight_number,
            'class': travel_class
        }
        response = self._make_request('/flights/baggage', data=data)
        return response

    def get_meal_options(self, flight_number: str, travel_class: str) -> List[Dict]:
        """Get available meal options"""
        data = {
            'flightNumber': flight_number,
            'class': travel_class
        }
        response = self._make_request('/flights/meals', data=data)
        return response.get('meals', [])

    def _is_token_valid(self) -> bool:
        """Check if the current access token is valid."""
        return self._access_token and self._token_expiry and datetime.now() < self._token_expiry

    def _refresh_access_token(self):
        """Refresh the access token."""
        self._access_token = None
        self._token_expiry = None 