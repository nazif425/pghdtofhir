
import requests
from . import ivr, cardio_data_collector, clear_session_data
from flask import g, Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL, BNode
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace
from rdflib.plugins.stores.sparqlstore import SPARQLStore
from datetime import datetime, date

from ..utils import unique_id, get_entity_name, is_timestamp, get_main_class, get_or_create_instances, build_fhir_resources
from ..utils import copy_instance, transform_data, send_authorisation_email, add_metadata_to_graph, verify_resources
from ..utils import store, insert_data_to_triplestore

# RDF namespace
pghdprovo = Namespace("https://w3id.org/pghdprovo/")
prov = Namespace("http://www.w3.org/ns/prov#")
foaf = Namespace("http://xmlns.com/foaf/0.1/gender")


query_header = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX s4wear: <https://saref.etsi.org/saref4wear/>
    PREFIX pghdprovo: <https://w3id.org/pghdprovo/>
    PREFIX : <https://w3id.org/wearpghdprovo/>
    PREFIX wearpghdprovo: <https://w3id.org/wearpghdprovo/>
"""

@ivr.before_request
def before_request_func():
    g.ses_data = {
        "validated" : False,
        "patient_id" : "",
        "practitioner_id" : "",
        "data" : {
            'heart_rate': None,
            'systolic_blood_pressure': None,
            'diastolic_blood_pressure': None,
            'collection_position': None,
            'collection_location': None,
            'collection_person': None,
            'collection_body_site': None
        }
    }
    # Perform tasks before each request handling
    #remove data if the call is ended
    if request.values.get('isActive', None) == 0:
        clear_session_data()
        abort(200, "Session ended")
    sessionId = request.values.get('sessionId', None)
    if sessionId:
        print("for with sess", request.values.get('sessionId', None))
        session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        if session:
            g.ses_data["data"] = session.data
            g.ses_data["validated"] = session.validated
            g.ses_data["practitioner_id"] = session.practitioner_id
            g.ses_data["patient_id"] = session.patient_id
        else:
            print("for without sess", request.values.get('sessionId', None))
            data = {
                "session_id": request.values.get('sessionId', None),
                "validated": g.ses_data["validated"],
                "data": g.ses_data["data"],
                "practitioner_id": g.ses_data["practitioner_id"],
                "patient_id": g.ses_data["patient_id"],
                "phone_number": request.values.get('callerNumber', None)
            }
            db.session.add(CallSession(**data))
            db.session.commit()

@ivr.after_request
def after_request_func(response):
        # Perform tasks after each request handling
    sessionId = request.values.get('sessionId', None)
    if sessionId:
        session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        if session:
            session.validated = g.ses_data["validated"]
            session.data = g.ses_data["data"]
            session.practitioner_id = g.ses_data["practitioner_id"]
            session.patient_id = g.ses_data["patient_id"]
            db.session.commit()
    return response

@ivr.route("/pghd_handler", methods=['POST','GET'])
def pghd_handler():
    
    with open('standard_responses/pghd_menu.xml') as f:
        response = f.read()
    return response


@ivr.route("/pghd_cardio_handler", methods=['POST'])
def pghd_cardio_handler():
    
    digits = request.values.get("dtmfDigits", None)
    print(digits)
    if digits and digits != '1':
        with open('standard_responses/invalid_entry.xml') as f:
            response = f.read()
        return response
    if digits == '1':
       return cardio_data_collector()
    else:
        return '<Response><Reject/></Response>'

@ivr.route("/patient_id_handler", methods=['POST'])
def patient_id_handler():
    
    patient_id = request.values.get("dtmfDigits", None)
    if verify_patient_id(patient_id):
        return cardio_data_collector()
    else:
        with open('standard_responses/invalid_patient_id.xml') as f:
            response = f.read()
        return response

@ivr.route("/heart_rate", methods=['POST'])
def heart_rate():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        g.ses_data["data"]['heart_rate'] = digits

    return cardio_data_collector()


@ivr.route("/systolic_blood_pressure", methods=['POST'])
def systolic_blood_pressure():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        g.ses_data["data"]['systolic_blood_pressure'] = digits

    return cardio_data_collector()


@ivr.route("/diastolic_blood_pressure", methods=['POST'])
def diastolic_blood_pressure():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        g.ses_data["data"]['diastolic_blood_pressure'] = digits

    return cardio_data_collector()

@ivr.route("/collection_position", methods=['POST'])
def collection_position():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == '1':
            g.ses_data["data"]['collection_position'] = 'Laying'
        elif digits == '2':
            g.ses_data["data"]['collection_position'] = 'Sitting'
        elif digits == '3':
            g.ses_data["data"]['collection_position'] = 'Standing'

    return cardio_data_collector()


@ivr.route("/collection_location", methods=['POST'])
def collection_location():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == '1':
            g.ses_data["data"]['collection_location'] = 'Home'
        elif digits == '2':
            g.ses_data["data"]['collection_location'] = 'Outside'

    return cardio_data_collector()


@ivr.route("/collection_person", methods=['POST'])
def collection_person():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == '1':
            g.ses_data["data"]['collection_person'] = 'Patient'
        elif digits == '2':
            g.ses_data["data"]['collection_person'] = 'Caregiver'
    
    return cardio_data_collector()

@ivr.route("/collection_body_site", methods=['POST'])
def collection_body_site():
    
    digits = request.values.get("dtmfDigits", None)
    if digits is not None:
        if digits == '1':
            g.ses_data["data"]['collection_body_site'] = 'Right arm'
        elif digits == '2':
            g.ses_data["data"]['collection_body_site'] = 'Left arm'
    
    return cardio_data_collector()


@ivr.route("/submit", methods=['POST'])
def submit():
    digits = request.values.get("dtmfDigits", None)
    # send_data_to_cedar()
    # send_data_to_openmrs()
    if digits == '1':
        heart_rate = g.ses_data["data"].get('heart_rate', None)
        systolic_bp = g.ses_data["data"].get('systolic_blood_pressure', None)
        diastolic_bp = g.ses_data["data"].get('diastolic_blood_pressure', None)
        collection_position = g.ses_data["data"].get('collection_position', None)
        collection_location = g.ses_data["data"].get('collection_location', None)
        collection_person = g.ses_data["data"].get('collection_person', None)
        collection_body_site = g.ses_data["data"].get('collection_body_site', None)
        timestamp =  datetime.now()

        new_records = [
            {
                'name': "Heart rate", 
                'value': heart_rate, 
                'code': "364075005", 
                'system': " http://snomed.info/sct",
            },
            {
                'name': "Systolic blood pressure", 
                'value': systolic_bp, 
                'code': "271649006", 
                'system': " http://snomed.info/sct",
            },
            {
                'name': "Diastolic blood pressure", 
                'value': diastolic_bp, 
                'code': "271650006", 
                'system': " http://snomed.info/sct",
            }
        ]
        

        phone_number = request.values.get('callerNumber', None)
        default_rdf = "static/rdf_files/wearpghdprovo-onto-template.ttl"
        
        # find existing rdf file for the patient
        #former_session = CallSession.query.filter(
        #    CallSession.phone_number==phone_number, 
        #    CallSession.rdf_file != None
        #).first()

        # Load the RDF graph
        #G = Graph()
        #if former_session:          
        #    G.parse(former_session.rdf_file, format="turtle")
        #else:
        #G.parse(default_rdf, format="turtle")
        new_g = Graph()
        triple_store = Graph(store=store)
        # triple_store_loc = "static/rdf_files/wearpghdprovo-onto-store.ttl"
        # triple_store.parse(triple_store_loc, format="turtle")

        # Find patient instance
        number_end = phone_number[-10:]
        find_patient = """
        SELECT ?patient ?number ?patientrelative
        WHERE {
            ?patient pghdprovo:phoneNumber ?number .
            ?patient a pghdprovo:Patient .
            FILTER(STRENDS(?number, '""" + number_end + """'))
            OPTIONAL {
                ?patientrelative prov:actedOnBehalfOf ?patient
            }
        }
        """
        
        patient_instance = None
        patient_relative = None

        result = triple_store.query(query_header + find_patient)
        
        for row in result:
            if row.patient:
                patient_instance = row.patient
            if row.patientrelative:
                patient_relative = row.patientrelative

        if not patient_instance:
            patient_instance = unique_id(pghdprovo.Patient)
            new_g.add((patient_instance, RDF.type, pghdprovo.Patient))
            new_g.add((patient_instance, pghdprovo.phoneNumber, Literal(phone_number)))
        
        if not patient_relative and collection_person == "Caregiver":
            patient_relative = unique_id(pghdprovo.PatientRelative)
            new_g.add((patient_relative, RDF.type, pghdprovo.PatientRelative))
            new_g.add((patient_relative, pghdprovo.relationship, Literal(collection_person)))
            new_g.add((patient_instance, pghdprovo.actedOnBehalfOf, patient_relative))
        
        # Create state instance. 
        state = unique_id(pghdprovo.State)
        new_g.add((state, RDF.type, pghdprovo.State))
        new_g.add((state, pghdprovo.posture, Literal(collection_position)))

        # Protocol instance. 
        protocol = unique_id(pghdprovo.Protocol)
        new_g.add((protocol, RDF.type, pghdprovo.Protocol))
        new_g.add((protocol, pghdprovo.bodySite, Literal(collection_body_site)))

        # location instance 
        location = unique_id(pghdprovo.ContextualInfo)
        new_g.add((location, RDF.type, pghdprovo.ContextualInfo))
        new_g.add((location, pghdprovo.locationOfPatient, Literal(collection_location)))
        
        for record in new_records:
            # Define unique PGHD instance name e.g PGHD.f47ac10b
            instance = unique_id(pghdprovo.PGHD)
            
            # Create an instance
            new_g.add((instance, RDF.type, pghdprovo.PGHD))
            
            # Adding data to instance
            new_g.add((instance, pghdprovo.name, Literal(record['name'])))
            new_g.add((instance, pghdprovo.value, Literal(record['value'])))
            new_g.add((instance, pghdprovo.dataSource, Literal('IVR')))
            time_str = timestamp.isoformat(timespec='seconds')
            new_g.add((instance, pghdprovo.hasTimestamp, Literal(time_str, datatype=XSD.dateTime)))
            
            # Record body position
            new_g.add((instance, pghdprovo.hasContextualInfo, state))
            
            # Record body side
            new_g.add((instance, pghdprovo.hasContextualInfo, protocol))

            # Record Location
            new_g.add((instance, pghdprovo.hasContextualInfo, location))

            # Assign patient instance to data
            new_g.add((instance, prov.wasAttributedTo, patient_instance))   

            # Assign the person who collected the data
            if collection_person == "Caregiver":
                new_g.add((instance, pghdprovo.wasCollectedBy, patient_relative))
            else:
                new_g.add((instance, pghdprovo.wasCollectedBy, patient_instance))
        
        # Save to remote tripple store
        insert_data_to_triplestore(new_g, store.update_endpoint)
        return '<Response><Say>Your data has been saved, thank you for your time</Say><Reject/></Response>'
    else:
        clear_session_data()
        return '<Response><Reject/></Response>'

@ivr.route('/test_fhir', methods=['GET'])
def test_fhir():
    #http://hapi.abdullahikawu.org/Patient?identifier=9e0003ae-4e5e-4442-aeab-838203fa2f5f
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}  
    response = requests.get(f"http://hapi.abdullahikawu.org/fhir/Patient?identifier=9e0003ae-4e5e-4442-aeab-838203fa2f5f",
            headers=headers)
    if response.status_code != 200:
        abort(500, f"Error querying resource: {response.text}")
    return jsonify(response.json())

@ivr.route('/data_request', methods=['POST'])
def data_request():
    data = request.get_json()
    if not data:
        abort(400, "Invalid request payload")
    
    if "IVR" not in data["request_type"]:
        abort(400, "Error, request type not provided.")
    verify_resources(data)
    instances = get_or_create_instances(data)
    
    patient = instances["patient"]
    practitioner = instances["practitioner"]
    ehr_system = instances["ehr_system"]
    identity = instances["identity"]
    organization = instances["organization"]

    if not data["meta-data"]["patient"].get("phone_number", None):
        abort(400, "Error, phone_number not provided.")

    destination_url = data.get("destination_url", None)
    phone_number = data["meta-data"]["patient"].get("phone_number", None)
    start_date = data.get("start_date", date.today().strftime("%Y-%m-%dT%H-%M-%S"))
    end_date = data.get("end_date", date.today().strftime("%Y-%m-%dT%H-%M-%S"))
    
    # Validate date
    if not is_timestamp(start_date, format="%Y-%m-%d"):
        start_date = date.today().strftime("%Y-%m-%dT00:00:00")
    else:
        # Convert date to datetime
        start_date = start_date + "T00:00:00"
    data["start_date"] = start_date

    # Validate date
    if not is_timestamp(end_date, format="%Y-%m-%d"):
        end_date = date.today().strftime("%Y-%m-%dT23:59:59")
    else:
        # Convert date to datetime
        end_date = end_date + "T23:59:59"
    data["end_date"] = end_date
    
    # Find existing rdf file for the patient
    former_session = CallSession.query.filter(
        CallSession.phone_number==phone_number, 
        CallSession.rdf_file != None
    ).first()

    if not former_session:          
        abort(404, f"No record found for {phone_number}")
    # Update data in graph with request meta-data
    
    new_g = Graph()
    triple_store = Graph(store=store)
    # triple_store_loc = "static/rdf_files/wearpghdprovo-onto-store.ttl"
    # triple_store.parse(triple_store_loc, format="turtle")
    
    request_data = Request(
            identity_id=identity.identity_id,
            startedAtTime=datetime.now(),
            endedAtTime=datetime.now(),
            description='Fetch patient data collected via a phone call.')
    db.session.add(request_data)
    db.session.commit()
    new_instances = add_metadata_to_graph(new_g, identity)
    result_prototype = {}
    found = False
    if new_instances.get("PGHDRequest", None):
        
        # Find patient instance
        number_end = phone_number[-10:]
        find_patient = f"""
        SELECT ?instance ?patient ?number ?timestamp
        WHERE {{
            ?patient pghdprovo:phoneNumber ?number .
            ?patient a pghdprovo:Patient .
            FILTER(STRENDS(?number, '{number_end}')) .
            ?instance prov:wasAttributedTo ?patient .
            ?instance pghdprovo:hasTimestamp  ?timestamp .
            FILTER (?timestamp >= "{start_date}"^^xsd:dateTime && ?timestamp <= "{end_date}"^^xsd:dateTime)
        }}
        """
        result = triple_store.query(query_header + find_patient)
        for row in result:
            found = True
            new_g.add((row.instance, prov.wasGeneratedBy, new_instances["PGHDRequest"]))
        
        # save data in remote store
        insert_data_to_triplestore(new_g, store.update_endpoint)
        
        result_prototype = {"IVR_link": '/' + triple_store_loc}
    
    if found:
        build_fhir_resources(triple_store, data)
    else:
        result_prototype = {"message": 'No result found for the given date.'}

    if data.get("destination_url", None):
        headers = {"Content-Type": "application/json"}
        # Make the POST request to Fitbit API
        response_data = requests.post(
                destination_url, 
                headers=headers, 
                data=result_prototype)
        
        if response_data.status_code != 200:
            print(f"data shared to {destination_url} successfully")
        else:
            print(f"Failed to share data to {destination_url} successfully")
    return jsonify(result_prototype)
        # to know the patient who authorize access to his account