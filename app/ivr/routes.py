
from . import ivr, cardio_data_collector, clear_session_data
from flask import g, Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace
from datetime import datetime, date

from ..utils import unique_id, get_entity_name, is_timestamp, get_main_class
from ..utils import copy_instance, transform_data, send_authorisation_email

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
        
        # define namespace
        pghdprovo = Namespace("https://w3id.org/pghdprovo/")
        prov = Namespace("http://www.w3.org/ns/prov#")
        foaf = Namespace("http://xmlns.com/foaf/0.1/gender")

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
        tripple_store = Graph()
        tripple_store_loc = "static/rdf_files/wearpghdprovo-onto-store.ttl"
        tripple_store.parse(tripple_store_loc, format="turtle")

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

        result = tripple_store.query(query_header + find_patient)
        
        for row in result:
            print(row.patient, row.patientrelative, sep=", ")
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
            
            # Create state instance. Record body position
            state = unique_id(pghdprovo.State)
            new_g.add((state, RDF.type, pghdprovo.State))
            new_g.add((state, pghdprovo.posture, Literal(collection_position)))
            new_g.add((instance, pghdprovo.hasContextualInfo, state))
            
            # Protocol instance. Record body side
            protocol = unique_id(pghdprovo.Protocol)
            new_g.add((protocol, RDF.type, pghdprovo.Protocol))
            new_g.add((protocol, pghdprovo.bodySite, Literal(collection_body_site)))
            new_g.add((instance, pghdprovo.hasContextualInfo, protocol))

            # location instance
            location = unique_id(pghdprovo.ContextualInfo)
            new_g.add((location, RDF.type, pghdprovo.ContextualInfo))
            new_g.add((location, pghdprovo.locationOfPatient, Literal(collection_location)))
            new_g.add((instance, pghdprovo.hasContextualInfo, location))

            # Assign patient instance to data
            new_g.add((instance, prov.wasAttributedTo, patient_instance))   

            # Assign the person who collected the data
            if collection_person == "Caregiver":
                new_g.add((instance, pghdprovo.wasCollectedBy, patient_relative))
            else:
                new_g.add((instance, pghdprovo.wasCollectedBy, patient_instance))
        # save rdf graph into to a file
        #str_time = timestamp.strftime("%Y-%m-%d-%H-%M-%S")
        #file_loc = "static/rdf_files/wearpghdprovo_" + str_time + ".ttl"
        #file_loc = former_session.rdf_file if former_session else file_loc
        #G.serialize(file_loc, format="turtle")
        # Insert rdf file dir to current session record
        #sessionId = request.values.get('sessionId', None)
        #current_session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        #if current_session:
        #    current_session.rdf_file = file_loc
        #    db.session.commit()
        #    clear_session_data()
        #else:
        #    print("Failed to save rdf file dir in database")
        #    return '<Response><Reject/></Response>'
        
        # Save to local tripple store
        for s, p, o in new_g:
            tripple_store.add((s, p, o))
        tripple_store.serialize(tripple_store_loc, format="turtle")
        return '<Response><Say>Your data has been saved, thank you for your time</Say><Reject/></Response>'
    else:
        clear_session_data()
        return '<Response><Reject/></Response>'