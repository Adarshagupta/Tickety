import os
import requests
from datetime import datetime
from typing import Dict, List, Optional

class IRCTCApi:
    def __init__(self):
        self.base_url = os.getenv('IRCTC_API_BASE_URL')
        self.api_key = os.getenv('IRCTC_API_KEY')
        self.agent_id = os.getenv('IRCTC_AGENT_ID')
        self.agent_password = os.getenv('IRCTC_AGENT_PASSWORD')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        })

    def _make_request(self, endpoint: str, method: str = 'POST', data: Dict = None) -> Dict:
        """Make a request to the IRCTC API"""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == 'POST':
                response = self.session.post(url, json=data)
            else:
                response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API Request Error: {str(e)}")
            return {'error': str(e)}

    def search_trains(self, from_station: str, to_station: str, journey_date: str) -> List[Dict]:
        """Search for trains between stations"""
        data = {
            'fromStation': from_station,
            'toStation': to_station,
            'journeyDate': journey_date,
            'agentId': self.agent_id
        }
        response = self._make_request('/bookingEnquiry', data=data)
        return response.get('trains', [])

    def check_availability(self, train_number: str, journey_date: str, quota: str = 'GN') -> List[Dict]:
        """Check seat availability for a train"""
        data = {
            'trainNumber': train_number,
            'journeyDate': journey_date,
            'quota': quota,
            'agentId': self.agent_id
        }
        response = self._make_request('/avlFareEnquiry', data=data)
        return response.get('availability', [])

    def book_ticket(self, booking_data: Dict) -> Dict:
        """Book train tickets"""
        booking_data['agentId'] = self.agent_id
        response = self._make_request('/bookingDetails', data=booking_data)
        return response

    def get_pnr_status(self, pnr: str) -> Dict:
        """Get PNR status"""
        data = {
            'pnrNumber': pnr,
            'agentId': self.agent_id
        }
        response = self._make_request('/pnrEnquiry', data=data)
        return response

    def cancel_ticket(self, pnr: str) -> Dict:
        """Cancel train ticket"""
        data = {
            'pnrNumber': pnr,
            'agentId': self.agent_id
        }
        response = self._make_request('/cancelBooking', data=data)
        return response

    def search_stations(self, query: str) -> List[Dict]:
        """Search for stations"""
        data = {
            'searchQuery': query,
            'agentId': self.agent_id
        }
        response = self._make_request('/stationSearch', data=data)
        return response.get('stations', [])

    def get_refund_details(self, pnr: str) -> Dict:
        """Get refund details for a cancelled ticket"""
        data = {
            'pnrNumber': pnr,
            'agentId': self.agent_id
        }
        response = self._make_request('/refundDetails', data=data)
        return response

    def get_booking_history(self, from_date: str, to_date: str) -> List[Dict]:
        """Get booking history between dates"""
        data = {
            'fromDate': from_date,
            'toDate': to_date,
            'agentId': self.agent_id
        }
        response = self._make_request('/fromDateToDate', data=data)
        return response.get('bookings', []) 