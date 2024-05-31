import numpy as np

from datetime import date, timedelta
import json
import random
import requests

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
    folder_id = 'https://repo.metadatacenter.org/folders/422ba135-4215-433a-b2d2-1d9a3fee7317' # If empty, instances are dumped in main folder 
    cedar_api_key = 'apiKey 7d1a85dbf1be5439b4b1332f860a29ad5377cbd43fe32a3962cb35c1cc62136b'
    bp_ontology_prefix = 'https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/' # TODO: Change this to bioportal?
    connect_ontology_prefix = 'https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/'
    
    cedar_bp_template = open('../templates/ivr_bp_cedar_template.json')
    cedar_template_connect = open('../templates/pghd_connect_template.json')
    
    bp_data = json.load(cedar_bp_template)
    connect_data = json.load(cedar_template_connect)

    for i in range(N):

        #data['PatientID']['@value'] = patientID
        
        bp_data['DataCollectedViaIVR']['@value'] = "Yes"
        bp_data['Date']['@value'] = instance_date.strftime('%Y-%m-%d')
        bp_data['hasPulseRate']['@value'] = str(int(np.random.normal(80, 10)))
        bp_data['hasSystolicBloodPressureValue']['@value'] = str(int(np.random.normal(100,5)))
        bp_data['hasDiastolicBloodPressureValue']['@value'] = str(int(np.random.normal(100,5)))
        bp_data['CollectionPosition']['@id'] = bp_ontology_prefix + random.choice(positions)
        bp_data['CollectionLocation']['@id'] = bp_ontology_prefix + random.choice(locations)
        bp_data['CollectionPerson']['@id'] = bp_ontology_prefix + random.choice(persons)
        bp_data['schema:name'] = f'BP_IVR_MockData_{i}'
        #cedar_template.close()

        response = requests.post(cedar_url, json=bp_data, 
                                 headers={'Content-Type': 'application/json',
                                          'Accept': 'application/json',
                                          'Authorization': cedar_api_key},
                                 params = {'folder_id': folder_id})
        #print(response.status_code)
        #print(json.dumps(response.json(), indent=2))
        cedar_data_URI = response.json()["@id"]
        
        
        

        connect_data['Patient']['@id'] = str(CEDAR_registration_ID)
        connect_data['collected_PGHD']['@id'] = cedar_data_URI
        connect_data['source_of_PGHD']['@id'] = str(connect_ontology_prefix + 'bp_ivr')
        connect_data['source_of_PGHD']['rdfs:label'] = str('bp_ivr')
        connect_data['schema:name'] = f'CNCT_MockData_{i}'

        response = requests.post(cedar_url, json=connect_data, 
                                 headers={'Content-Type': 'application/json',
                                          'Accept': 'application/json',
                                          'Authorization': cedar_api_key},
                                 params = {'folder_id': folder_id})
        #print(response.status_code)
        #print(json.dumps(response.json(), indent=2))
        #bp_data, connect_data = clear_data(bp_data, connect_data)
        print(f'{i+1}/{N}')#, end='\r')


def clear_data(bp_data, connect_data):
    bp_data = None
    connect_data = None
    return bp_data, connect_data

def create_fitbit_instances():
    pass

def main():
    patientID = '1234'
    CEDAR_registration_ID = 'https://repo.metadatacenter.org/template-instances/5c3c4a9d-cf6c-4dcb-a2f4-935e4c7fd1f7'
    N = 5

    create_bp_ivr_instances(N, patientID, CEDAR_registration_ID)


if __name__ == '__main__':
    main()