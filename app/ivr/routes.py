
import requests
from . import ivr, cardio_data_collector, clear_session_data
from flask import g, Flask, current_app, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL, BNode
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace
from rdflib.plugins.stores.sparqlstore import SPARQLStore
from datetime import datetime, date
from ..utils import generate_sparql_query, transform_query_result, send_access_code, filter_prepared_data
from ..utils import unique_id, get_entity_name, is_timestamp, get_main_class, get_or_create_instances, build_fhir_resources
from ..utils import copy_instance, transform_data, send_authorisation_email, add_metadata_to_graph, verify_resources
from ..utils import store, insert_data_to_triplestore, generate_unique_5_digit, get_timestamps_from_graph

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
        #clear_session_data()
        abort(200, "Session ended")
    sessionId = request.values.get('sessionId', None)
    if sessionId:
        print("for with sess", request.values.get('sessionId', None))
        call_session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        if call_session:
            g.ses_data["data"] = call_session.data
            g.ses_data["validated"] = call_session.validated
            g.ses_data["practitioner_id"] = call_session.practitioner_id
            g.ses_data["patient_id"] = call_session.patient_id
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
        call_session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        if call_session:
            call_session.validated = g.ses_data["validated"]
            call_session.data = g.ses_data["data"]
            call_session.practitioner_id = g.ses_data["practitioner_id"]
            call_session.patient_id = g.ses_data["patient_id"]
            call_session.completed_at = datetime.now()
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
            g.ses_data["data"]['collection_position'] = 'Lying'
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

@ivr.route('/data', methods=['GET'])
def data():
    data = {}
    if request.method == 'GET':
        private_key = request.args.get("private_key", None)
        public_key = request.args.get("public_key", None)
        if not private_key or not public_key:
            return jsonify({"message": "Invalid payload, access key(s) not provided.", "status": 400}), 400
    auth_session = AuthSession.query.filter_by(private_key=private_key, public_key=public_key).first()
    if auth_session is None:
        return jsonify({"message": "Error, could not identify request id", "status": 400}), 400
    
    identity_id = auth_session.identity_id
    identity = Identity.query.get_or_404(identity_id)
    patient = identity.patient
    practitioner = identity.practitioner
    data = auth_session.data.get("request_data", None)
    
    metadata = {}

    phone_number = data["meta-data"]["patient"].get("phone_number", None)
    if not phone_number:
        return jsonify({"message": "Error, phone_number not provided.", "status": 400}), 400
    
    if phone_number[0] != '+':
        abort(400, "Error, invalid phone_number.")
    
    start_date = data.get("start_date", None)
    end_date = data.get("end_date", None)
    
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
    
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%S")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S")
    
    # Find calls for the within the datetime range
    call_sessions = CallSession.query.filter(
        CallSession.completed_at.between(start_date_obj, end_date_obj),
        CallSession.phone_number==phone_number, 
    ).all()

    if not call_sessions:
        return jsonify({
            "message": f"No record found for {phone_number} with given date range",
            "status": 404
        }), 404
    
    # Prepare Fetched data 
    sessions_data = []
    for call_session in call_sessions:
        sessions_data.append({
            "collection_position": call_session.data.get('collection_position', None) or "",
            "collection_location": call_session.data.get('collection_location', None) or "",
            "collection_person": call_session.data.get('collection_person', None) or "",
            "collection_body_site": call_session.data.get('collection_body_site', None) or "",
            "timestamp": call_session.completed_at,
            "new_records": [
                {
                    'name': "heart_rate", 
                    'value': call_session.data.get('heart_rate', None) or 0
                },
                {
                    'name': "systolic_blood_pressure", 
                    'value': call_session.data.get('systolic_blood_pressure', None) or 0
                },
                {
                    'name': "diastolic_blood_pressure", 
                    'value': call_session.data.get('diastolic_blood_pressure', None) or 0
                }
            ]
        })

    g = Graph()
    g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")
    new_g = Graph()
    triple_store = Graph(store=store)
    result = {}
    
    # Find exist data to prevent duplicate
    
    # Get all timestamps for the given data request
    user_id = data["meta-data"]["patient"].get("user_id", None)
    source = data['request_type']
    timestamps = get_timestamps_from_graph(triple_store, source, user_id, request_data_type=None)
    
    # Remove existing data already in triple store
    sessions_data = filter_prepared_data(sessions_data, timestamps, date_key="timestamp")
    
    if len(sessions_data):
        request_info = Request(
            identity_id=identity.identity_id,
            startedAtTime=datetime.now(),
            description=f'Fetch patient data from {data["request_type"]}',
        )
        db.session.add(request_info)
        db.session.flush()
        
        new_instances = add_metadata_to_graph(new_g, identity)

        patient_instance = new_instances["Patient"]

        for row in sessions_data:
            patient_relative = None
            if not patient_relative and collection_person == "Caregiver":
                patient_relative = unique_id(pghdprovo.PatientRelative)
                new_g.add((patient_relative, RDF.type, pghdprovo.PatientRelative))
                new_g.add((patient_relative, pghdprovo.relationship, Literal(row["collection_person"])))
                new_g.add((patient_instance, pghdprovo.actedOnBehalfOf, patient_relative))
        
            # Create state instance. 
            state = unique_id(pghdprovo.State)
            new_g.add((state, RDF.type, pghdprovo.State))
            new_g.add((state, pghdprovo.posture, Literal(row["collection_position"])))

            # Protocol instance. 
            protocol = unique_id(pghdprovo.Protocol)
            new_g.add((protocol, RDF.type, pghdprovo.Protocol))
            new_g.add((protocol, pghdprovo.bodySite, Literal(row["collection_body_site"])))

            # location instance 
            location = unique_id(pghdprovo.ContextualInfo)
            new_g.add((location, RDF.type, pghdprovo.ContextualInfo))
            new_g.add((location, pghdprovo.locationOfPatient, Literal(row["collection_location"])))
        
            new_records = row["new_records"]
            for record in new_records:
                # Define unique PGHD instance name e.g PGHD.f47ac10b
                instance = unique_id(pghdprovo.PGHD)
                
                # Create an instance
                new_g.add((instance, RDF.type, pghdprovo.PGHD))
                
                # Adding data to instance
                new_g.add((instance, pghdprovo.name, Literal(record['name'])))
                new_g.add((instance, pghdprovo.value, Literal(record['value'])))
                new_g.add((instance, pghdprovo.dataSource, Literal('IVR - BPM')))
                time_str = row["timestamp"].isoformat(timespec='seconds')
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

                # Add property annotations to instance
                for s, p, o in g.triples((pghdprovo[record['name']], RDF.type, OWL.DatatypeProperty)):
                    for annoteProp in [RDFS.label, RDFS.comment]:
                        value = g.value(
                            subject=pghdprovo[record['name']], 
                            predicate=annoteProp)
                        if value:
                            new_g.add((instance, annoteProp, value))
                    break
        
        # Save to remote tripple store
        result["triplestore"] = insert_data_to_triplestore(new_g, store.update_endpoint)
        # Save to remote fhir server
        result["fhir"] = build_fhir_resources(triple_store, data)

        request_info.endedAtTime = datetime.now()
        db.session.commit()
    # Change data request status
    auth_session.data = {"request_data": data, "complete": True}
    db.session.commit()
    print(auth_session.data)
    #except Exception as e:
    #request_info.endedAtTime = datetime.now()
    #db.session.commit()
    #return jsonify({"message": str(e)}), 500
    
    # Send access key to patient
    email = data.get("meta-data", {}).get("patient", {}).get("email", None)
    org_name = data.get("meta-data", {}).get("organization", {}).get("name", "")
    if not send_access_code(email, private_key, org_name, data_source="IVR"):
        return jsonify({
            'message': "An error occurred. Email request to patient failed.",
            'status': 500
        }), 500
    return jsonify({
        'message': f"Authorization request/access key sent successfully to {email}.",
        'public_key': auth_session.public_key,
        'status': 200
    }), 200
    #return redirect(url_for("ivr.data_request", private_key=private_key, public_key=public_key))
    

@ivr.route('/data_request', methods=['POST', 'GET'])
def data_request():
    if request.method == 'GET':
        private_key = request.args.get("private_key", None)
        public_key = request.args.get("public_key", None)
        if not private_key or not public_key:
            return jsonify({"message": "Invalid payload, access key(s) not provided.", "status": 400}), 400
        auth_session = AuthSession.query.filter_by(private_key=private_key, public_key=public_key).first()
        
        if auth_session is None:
            return jsonify({"message": "Error, Invalid access key(s)", "status": 403}), 403
        
        request_data = auth_session.data.get("request_data", None)
        print(request_data)
        if not auth_session.data.get("complete", None):
            # fetch data if fitbit token for patient available
            if "IVR" in request_data.get("request_type", None):
                query_params = {
                    'private_key': private_key,
                    'public_key': public_key
                }
                with current_app.test_request_context(
                    '/data',
                    method='GET',
                    query_string=query_params
                ):
                    return data()

        # Generate the SPARQL query
        sparql_query = generate_sparql_query(request_data)

        # Execute the SPARQL query (assuming you have a function to do this)
        triple_store = Graph(store=store)
        query_result = triple_store.query(sparql_query)
        # For demonstration, let's assume the query result is as follows:

        # Transform the query result into the desired format
        records = transform_query_result(query_result)
        
        print(records)
        print(f"Data shared successfully")
        return jsonify({"data": records, "status": 200}), 200

    elif request.method == 'POST':
        request_data = request.get_json()
        if request_data.get("request_data_type", None) == "heartrate":
            request_data["request_data_type"] = "heart_rate"
        if not request_data:
            return jsonify({"message": f"Invalid request payload", "status": 400}), 400
        
        if "IVR" not in request_data["request_type"]:
            return jsonify({"message": f"Error, request type not provided.", "status": 400}), 400
        verify_resources(request_data)
        instances = get_or_create_instances(request_data)
        
        patient = instances["patient"]
        practitioner = instances["practitioner"]
        ehr_system = instances["ehr_system"]
        identity = instances["identity"]
        organization = instances["organization"]

        private_key = str(generate_unique_5_digit())
        public_key = str(generate_unique_5_digit())
        authsession_data = {
            "private_key": private_key,
            "public_key": public_key,
            "patient_id": patient.patient_id, 
            "identity_id": identity.identity_id,
            "data": {'request_data': request_data, "complete": False}
        }

        auth_session = AuthSession(**authsession_data)
        db.session.add(auth_session)
        db.session.commit()
        query_params = {
            'private_key': private_key,
            'public_key': public_key
        }
        with current_app.test_request_context(
            '/data',
            method='GET',
            query_string=query_params
        ):
            return data()
        #return redirect(url_for("ivr.data", private_key=private_key, public_key=public_key))
        