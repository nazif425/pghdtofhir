from flask import Flask, request
import requests
from datetime import datetime
import json
from urllib import parse

from rdflib import Graph, Namespace
from rdflib.namespace import XSD
from rdflib.plugins.sparql import prepareQuery

app = Flask(__name__)
registrations_file = 'triple_store/registrations.ttl'

meta_data = {'phone_number': None,
             'cedar_registration_URI': None}

cardio_data = {'heart_rate': None,
               'systolic_blood_pressure': None,
               'diastolic_blood_pressure': None,
               'collection_position': None,
               'collection_location': None,
               'collection_person': None}


def cardio_data_collector():
    if cardio_data['heart_rate'] is None:
        with open('ivr_standard_responses/heart_rate.xml') as f:
            response = f.read()
        return response
    elif cardio_data['systolic_blood_pressure'] is None:
        with open('ivr_standard_responses/systolic_blood_pressure.xml') as f:
            response = f.read()
        return response
    elif cardio_data['diastolic_blood_pressure'] is None:
        with open('ivr_standard_responses/diastolic_blood_pressure.xml') as f:
            response = f.read()
        return response
    elif cardio_data['collection_position'] is None:
        with open('ivr_standard_responses/collection_position.xml') as f:
            response = f.read()
        return response
    elif cardio_data['collection_location'] is None:
        with open('ivr_standard_responses/collection_location.xml') as f:
            response = f.read()
        return response
    elif cardio_data['collection_person'] is None:
        with open('ivr_standard_responses/collection_person.xml') as f:
            response = f.read()
        return response
    else:
        response =   '<Response>'
        response += f'<Say>Your provided heartrate is {cardio_data["heart_rate"]}</Say>'
        response += f'<Say>Your provided systolic bloodpressure is {cardio_data["systolic_blood_pressure"]}</Say>'
        response += f'<Say>Your provided diastolic bloodpressure is {cardio_data["diastolic_blood_pressure"]}</Say>'
        response +=  '<GetDigits timeout="30" finishOnKey="#" callbackUrl="/submit">'
        response +=  '<Say>If this is correct and you want to submit, press one followed by the hash sign. If you want to abort press two followed by the hash sign</Say>'
        response +=  '</GetDigits></Response>'

        return response


def send_data_to_cedar():
    cedar_url = 'https://resource.metadatacenter.org/template-instances'
    with open('../.secrets.json') as secrets:
        cedar_api_key = json.load(secrets)["authkey_RENS"]
    current_time = datetime.now()

    ontology_prefix = 'https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/' 
    cedar_template = open('templates/ivr_bp_cedar_template.json')
    bp_data = json.load(cedar_template)

    bp_data['DataCollectedViaIVR']['@value'] = 'Yes'
    bp_data['Date']['@value'] = current_time.strftime('%Y-%m-%d')
    bp_data['Pulse Number']['@value'] = str(cardio_data['heart_rate'])
    bp_data['Blood Pressure (Systolic)']['@value'] = str(cardio_data['systolic_blood_pressure'])
    bp_data['Blood Pressure (Diastolic)']['@value'] = str(cardio_data['diastolic_blood_pressure'])
    bp_data['CollectionPosition']['@value'] = ontology_prefix + str(cardio_data['collection_position'])
    bp_data['CollectionLocation']['@value'] = ontology_prefix + str(cardio_data['collection_location'])
    bp_data['CollectionPerson']['@value'] = ontology_prefix + str(cardio_data['collection_person'])
    bp_data['schema:name'] = f"PGHD_BP {current_time.strftime('%Y-%m-%d')}"
    cedar_template.close()

    response = requests.post(cedar_url, json=bp_data, 
                             headers={'Content-Type': 'application/json',
                                      'Accept': 'application/json',
                                      'Authorization': cedar_api_key})

    cedar_data_URI = response['@id']

    cedar_template_connect = open('templates/pghd_connect_template.json')
    connect_ontology_prefix = 'https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/'
    connect_data = json.load(cedar_template_connect)

    connect_data['Patient']['@id'] = str(meta_data['cedar_registration_URI'])
    connect_data['collected_PGHD']['@id'] = cedar_data_URI
    connect_data['source_of_PGHD']['@id'] = str(connect_ontology_prefix + 'bp_ivr')
    connect_data['source_of_PGHD']['rdfs:label'] = str('bp_ivr')
    connect_data['schema:name'] = f"PGHD_BP CNT {current_time.strftime('%Y-%m-%d')}"

    requests.post(cedar_url, json=connect_data, 
                  headers={'Content-Type': 'application/json',
                           'Accept': 'application/json',
                           'Authorization': cedar_api_key})

    clear_data()


def clear_data():
    clear_cardio_data()
    clear_meta_data()

def clear_cardio_data():
    cardio_data['heart_rate'] = None
    cardio_data['systolic_blood_pressure'] = None
    cardio_data['diastolic_blood_pressure'] = None
    cardio_data['collection_position'] = None
    cardio_data['collection_location'] = None
    cardio_data['collection_person'] = None

def clear_meta_data():
    meta_data['phone_number'] = None
    meta_data['cedar_registration_URI'] = None


def authenticate(passcode, local_registrations=False):
    # Import registrations. This should ideally be done through remote querying on AllegroGraph so the data and script are fully separate.
    if passcode is None:
        return False, "No password was entered" 

    # This clause can be used if the list of registered patients is stored localy at clinic side and can be easily retrieved (or queried through e.g. AG)
    # For the purpose of the pilot we store all data on CEDAR and import from there 
    g = Graph()
    if local_registrations:
        g.parse(registrations_file)
    else:
        with open('../.secrets.json') as secrets:
            cedar_api_key = json.load(secrets)["authkey_RENS"]

        cedar_url = "https://resource.metadatacenter.org/template-instances/"
        # NOTE: This is only for one patient!!
        patient_uri = parse.quote_plus("https://repo.metadatacenter.org/template-instances/f33ce769-87be-4d08-b55d-01026eae057c")
        headers = {"accept": "application/json", "authorization": cedar_api_key}

        response = requests.get(cedar_url+patient_uri, headers=headers)
        g.parse(data=response.json(), format='json-ld')


    query_string = f"""
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>     
        SELECT ?id ?code ?patient_id
        WHERE{{
            ?id <http://schema.org/isBasedOn>  <https://repo.metadatacenter.org/templates/f49d788e-f611-4525-90e9-dd21204b51fa> ;
                pghdc:phoneNumber "{meta_data['phone_number']}" ;
                pghdc:hiddenCode ?code ;
                pghdc:patientID ?patient_id .
        }}
        """

    # Execute query on graph using RDFLib. Check performance in case of large store
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    query = prepareQuery(query_string, initNs={'pghdc': pghdc, 'xsd': XSD})
    res = g.query(query)

    # Error catching -> can expand this depending on need
    if len(res) == 0:
        return False, "This phonenumber + password combination is not known. Please check this and try again."
    elif len(res) > 1:
        return False, "There are multiple registrations connected to this phonenumber. Please check this with your caregiver."
    
    for row in res:
        if str(row.code) == str(passcode):
            meta_data['cedar_registration_URI'] = row.id
            return True, f"Welcome, your ID is {row.patient_id}" 
        else:
            return False, "2 This phonenumber + password combination is not known. Please check this and try again."


@app.route("/pghd_handler", methods=['POST'])
def pghd_handler():
    with open('ivr_standard_responses/pghd_menu.xml') as f:
        response = f.read()
    return response


@app.route("/authenticate", methods=['POST'])
def pghd_authenticator():
    digits = request.values.get("dtmfDigits", None)
    authenticated, response_text = authenticate(digits)

    if authenticated:
        # Right now we just continue to BP. We could potentially fork here depending on which devices the user has
        bp_handler = "https://www.pghd.renskievit.com/ivr/pghd_cardio_handler"

        response  =  "<Response>"
        response += f"<Say>{response_text}</Say>"
        response += f"<Redirect>{bp_handler}</Redirect>"
        response +=  "</Response>"
    else:  
        response  =  "<Response>"
        response += f"<Say>{response_text}</Say>"
        response +=  "<Reject/>"
        response +=  "</Response>"

    return response


@app.route("/pghd_cardio_handler", methods=['POST'])
def pghd_cardio_handler():
    return cardio_data_collector()


@app.route("/heart_rate", methods=['POST'])
def heart_rate():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        cardio_data['heart_rate'] = digits

    return cardio_data_collector()


@app.route("/systolic_blood_pressure", methods=['POST'])
def systolic_blood_pressure():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        cardio_data['systolic_blood_pressure'] = digits

    return cardio_data_collector()


@app.route("/diastolic_blood_pressure", methods=['POST'])
def diastolic_blood_pressure():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        cardio_data['diastolic_blood_pressure'] = digits

    return cardio_data_collector()


@app.route("/collection_position", methods=['POST'])
def collection_position():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == 1:
            cardio_data['collection_position'] = 'Laying'
        elif digits == 2:
            cardio_data['collection_position'] = 'Sitting'
        elif digits == 3:
            cardio_data['collection_position'] = 'Standing'

    return cardio_data_collector()


@app.route("/collection_location", methods=['POST'])
def collection_location():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == 1:
            cardio_data['collection_location'] = 'Home'
        elif digits == 2:
            cardio_data['collection_location'] = 'Outside'

    return cardio_data_collector()


@app.route("/collection_person", methods=['POST'])
def collection_person():
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == 1:
            cardio_data['collection_person'] = 'Patient'
        elif digits == 2:
            cardio_data['collection_person'] = 'Caregiver'
    
    return cardio_data_collector()


@app.route("/submit", methods=['POST'])
def submit():
    digits = request.values.get("dtmfDigits", None)
    if digits == '1':
        send_data_to_cedar()
        clear_data()
        return '<Response><Say>Your data has been saved, thank you for your time</Say><Reject/></Response>'
    else:
        clear_data()
        return '<Response><Reject/></Response>'


if __name__ == '__main__':
    app.run(debug=True, port=2024)
