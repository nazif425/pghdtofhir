import numpy as np

from datetime import date, timedelta
import json
import random
from flask import requests

def create_bp_ivr_instances(N, patientID, CEDAR_registration_ID):
    """Create N CEDAR instances of data with random values for the mock dashboard.
    First setup allows for one observation daily."""

    positions = ['Laying', 'Sitting', 'Standing']
    locations = ['Home', 'Outside']
    persons = ['Patient', 'Caregiver']

    # One observation per day, leading up to the day (as of coding) 2024-05-28
    today = date(2024, 5, 28)
    delta = timedelta(days=1)
    instance_date = today - N*delta

    # Below code copied from ivr_handler. Send data
    cedar_url = 'https://resource.metadatacenter.org/template-instances'
    cedar_api_key = 'apiKey 62838dcb5b6359a1a93baeeef907669813ec431437b168efde17a61c254b3355'
    ontology_prefix = 'https://github.com/abdullahikawu/PGHD/tree/main/vocabularies/' # TODO: Change this!
    cedar_template = open('../templates/ivr_bp_cedar_template.json')

    for i in range(N):
        data = json.load(cedar_template)
        data['PatientID']['@value'] = patientID
        data['DataCollectedViaIVR']['@value'] = 'Yes'
        data['Date']['@value'] = instance_date.strftime('%Y-%m-%d')
        data['Pulse Number']['@value'] = np.random.normal(80, 10)
        data['Blood Pressure (Systolic)']['@value'] = np.random.normal(100,5)
        data['Blood Pressure (Diastolic)']['@value'] = np.random.normal(100,5)
        data['CollectionPosition']['@value'] = ontology_prefix + random.choice(positions)
        data['CollectionLocation']['@value'] = ontology_prefix + random.choice(locations)
        data['CollectionPerson']['@value'] = ontology_prefix + random.choice(persons)
        data['schema:name'] = f'BP_IVR_MockData_{i}'
        cedar_template.close()

        requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                    'Accept': 'application/json',
                                                    'Authorization': cedar_api_key})
        data = None # Clear data

        # TODO: Extract template URI from the response to this request


        cedar_template_connect = open('templates/pghd_connect_template.json')  # TODO - Add this
        data = json.load(cedar_template_connect)
        # TODO Populate template

        instance_date += delta

def create_fitbit_instances():
    pass

def main():
    patientID = '1234'
    CEDAR_registration_ID = 'https://repo.metadatacenter.org/template-instances/5c3c4a9d-cf6c-4dcb-a2f4-935e4c7fd1f7'
    N = 50

    create_bp_ivr_instances(N, patientID, CEDAR_registration_ID)


if __name__ == '__main__':
    main()