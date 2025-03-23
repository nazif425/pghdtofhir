import sys, os, random, base64, hashlib, secrets, random, string, requests, uuid, json, smtplib
import fitbit
from urllib.parse import urlencode
from os import environ
from flask import Flask, current_app, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from flask import make_response
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from fhir.resources.patient import Patient as fhirPatient
from fhir.resources.humanname import HumanName
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace
from rdflib.plugins.stores.sparqlstore import SPARQLStore
from . import wearable, get_fitbit_data, store_tokens_in_db, load_tokens_from_db, fetch_fitbit_data, process_and_send_data
from . import refresh_and_store_tokens, generate_fitbit_auth_url, generate_healthconnect_auth_url, prepare_data
from ..utils import unique_id, get_entity_name, is_timestamp, get_main_class, REDIRECT_URI, add_metadata_to_graph
from ..utils import CLIENT_ID, CLIENT_SECRET, transform_data, send_authorisation_email, get_or_create_instances
from ..utils import verify_resources, build_fhir_resources, store, insert_data_to_triplestore, send_access_code
from ..utils import generate_sparql_query, transform_query_result, generate_unique_5_digit

@wearable.route('/cancel_fitbit_auth', methods=['GET'])
def cancel_authorization():
    if not session.get('patient_id', None):
        return redirect(url_for('portal.patient_login'))
    
    patient = Patient.query.get_or_404(session.get('patient_id', None))
    deleted_count = Fitbit.query.filter_by(patient_id=patient.patient_id).delete()
    db.session.commit()
    flash('Fitbit device disconnected successfully')
    return redirect(url_for('portal.patient_dashboard'))


@wearable.route('/verify_access_code', methods=['POST'])
def auth_status():
    if request.method != 'POST':
        return jsonify({
                "message": "Invalid request method.",
                "status": 400
            }), 400
        data = request.get_json()
        print(data)
        if not data:
            return jsonify({"message": "Invalid payload", "status": 400}), 400
        private_key = request.args.get("private_key", None)
        public_key = request.args.get("public_key", None)
        if not private_key or not public_key:
            return jsonify({"message": "Invalid payload, access key(s) not provided.", "status": 400}), 400
        auth_session = AuthSession.query.filter_by(private_key=private_key, public_key=public_key).first()
        if auth_session is None:
            return jsonify({
                "message": "Invalid access code.", 
                "authorized": False,
                "status": 404
            }), 404
        else:
            return jsonify({
                "message": "Access code is valid",
                "authorized": True,
                "status": 200
            }), 200

@wearable.route('/data_request', methods=['POST', 'GET'])
def data_request():
    if request.method == 'GET':
        private_key = request.args.get("private_key", None)
        public_key = request.args.get("public_key", None)
        if not private_key or not public_key:
            return jsonify({"message": "Invalid payload, access key(s) not provided.", "status": 400}), 400
        auth_session = AuthSession.query.filter_by(private_key=private_key, public_key=public_key).first()
        if auth_session is None:
            return jsonify({"message": "Error, Invalid access key", "status": 403}), 403
        
        patient_id = auth_session.patient_id
        patient = Patient.query.filter_by(patient_id=patient_id).first()
        if patient is None:
            return jsonify({"message": "An error occured, patient does not exist", "status": 500}), 500
        request_data = auth_session.data.get("request_data", None)
        
        print(request_data)
        if not auth_session.data.get("complete", None):
            # fetch data if fitbit token for patient available
            if request_data.get("request_type", None) == "fitbit" and load_tokens_from_db(patient.patient_id):
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
            return jsonify({"message": "Data request in progress. Data not available yet.", "status": 202}), 202

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
        if not request_data:
            response = jsonify({
                'message': "Invalid request payload",
                'status': 400
            })
            abort(make_response(response, 400))
        
        if request_data.get("request_type", "") not in ["fitbit", "healthconnect"]:
            response = jsonify({
                'message': "Error, request type not provided.",
                'status': 400
            })
            abort(make_response(response, 400))
        
        verify_resources(request_data)
        instances = get_or_create_instances(request_data)
        
        patient = instances["patient"]
        practitioner = instances["practitioner"]
        ehr_system = instances["ehr_system"]
        identity = instances["identity"]
        organization = instances["organization"]
        
        # Validate date
        start_date = request_data["start_date"]
        end_date = request_data["end_date"]
        if not is_timestamp(start_date, format="%Y-%m-%d"):
            start_date = date.today().strftime("%Y-%m-%dT00:00:00")
        else:
            # Convert date to datetime
            start_date = start_date + "T00:00:00"

        if not is_timestamp(end_date, format="%Y-%m-%d"):
            end_date = date.today().strftime("%Y-%m-%dT23:59:59")
        else:
            # Convert date to datetime
            end_date = end_date + "T23:59:59"
        
        request_data["start_date"] = start_date
        request_data["end_date"] = end_date
            
        # map request request data type from unified keys to different sources keys
        if request_data["request_type"] == "fitbit":
            if request_data["request_data_type"] == "sleep":
                request_data["request_data_type"] = "sleepDuration"
            elif request_data["request_data_type"] == "heartrate":
                request_data["request_data_type"] = "restingHeartRate"
        if request_data["request_type"] == "healthconnect":
            if request_data["request_data_type"] == "sleep":
                request_data["request_data_type"] = "SLEEP_SESSION"
            elif request_data["request_data_type"] == "steps":
                request_data["request_data_type"] = "STEPS"
            elif request_data["request_data_type"] == "heartrate":
                request_data["request_data_type"] = "HEART_RATE"
        
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
        if request_data["request_type"] == "fitbit":
            if load_tokens_from_db(patient.patient_id):
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
            data_source = "Fitbit"
            auth_link = generate_fitbit_auth_url(auth_session)
        elif request_data["request_type"] == "healthconnect":
            data_source = "HealthConnect"
            auth_link = generate_healthconnect_auth_url(auth_session, request_data)
        
        # reaponse with public key
        email = request_data.get("meta-data", {}).get("patient", {}).get("email", "")
        org_name = request_data.get("meta-data", {}).get("organization", {}).get("name", "")
        print(email)
        if not send_authorisation_email(email, auth_link, org_name, data_source=data_source):
            return jsonify({
                'message': "An error occurred. Email request to patient failed.",
                'status': 500
            }), 500
        return jsonify({
            'message': f"Authorization request/access key sent successfully to {email}.",
            'public_key': public_key,
            'status': 200
        }), 200

@wearable.route('/request_fitbit_auth', methods=['GET'])
def request_authorization():
    # to know the patient who authorize access to his account
    if not session.get('patient_id', None):
        return redirect(url_for('portal.patient_login'))
    patient_id = session.get('patient_id', None)
    auth_url = generate_fitbit_auth_url(patient_id=patient_id)
    print(auth_url)
    
    # Redirect the user to the Fitbit 
    return jsonify({
        'auth_url': auth_url,
    })

@wearable.route('/fitbit_auth_callback', methods=['GET'])
def get_access_token():
    # After the user has granted access, the authorization server
    # will redirect the user to the redirect_uri with the authorization code
    authorization_code = request.args.get('code', None)
    state = request.args.get('state', None)
    if not state:
        response = jsonify({
            'message': "state not provided",
            'status': 404
        })
        abort(make_response(response, 404))
    auth_session = AuthSession.query.filter_by(private_key=state).first()
    if auth_session is None:
        flash('Sorry, could not authenticate user.', 'danger')
        return redirect(url_for('portal.patient_dashboard'))
    
    code_verifier = auth_session.code_verifier
    patient_id = auth_session.patient_id
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if patient is None:
        flash('Sorry, could not authenticate user.', 'danger')
        return redirect(url_for('portal.patient_dashboard'))
    
    token_url = "https://api.fitbit.com/oauth2/token"
    
    # Create Basic Authorization header
    client_creds = f"{CLIENT_ID}:{CLIENT_SECRET}"
    basic_token = base64.b64encode(client_creds.encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # Prepare the data payload
    payload = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier
    }
    
    print(payload)
    # Make the POST request to Fitbit API
    token_response = requests.post(token_url, headers=headers, data=urlencode(payload))
    
    if token_response.status_code == 200:
            # Parse the JSON response
        token_data = token_response.json()
        
        token_dict = {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_type": token_data.get("token_type"),
            "expires_in": token_data.get("expires_in")
        }
        print(token_dict)
        store_tokens_in_db(patient_id, token_dict)
    else:
        print(token_response)
        response = jsonify({
            'message': "Failed to fetch access token",
            'status': token_response.status_code
        })
        abort(make_response(response, token_response.status_code))
    if not session.get('patient_id', None):
        session["request_data"] = auth_session.data.get('request_data', None)
         
        private_key = auth_session.private_key
        public_key = auth_session.public_key
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
    return redirect(url_for('portal.patient_dashboard'))

@wearable.route('/data', methods=['GET', 'POST'])
def data():
    def all_zeros(data_list, key):
        """
        Returns True if every value for the given key in the list of dictionaries is 0.
        
        :param data_list: List of dictionaries
        :param key: The key to check in each dictionary
        :return: True if all values are 0, otherwise False
        """
        return all(int(d.get(key, 0)) == 0 for d in data_list)
    
    data = {}
    if request.method == 'GET':
        private_key = request.args.get("private_key", None)
        public_key = request.args.get("public_key", None)
        if not private_key or not public_key:
            return jsonify({"message": "Invalid payload, access key(s) not provided.", "status": 400}), 400
    elif request.method == 'POST':
        data = request.get_json()
        print(data)
        if not data:
            return jsonify({"message": "Invalid payload", "status": 400}), 400
        metadata = data.get("metadata", None)
        if not metadata:
            return jsonify({"message": "Invalid payload, metadata missing.", "status": 400}), 400
        if not metadata.get("user_id", None):
            return jsonify({"message": "Invalid payload, user_id not provided.", "status": 400}), 400
        private_key = metadata.get("user_id", None)
    auth_session = AuthSession.query.filter_by(private_key=private_key).first()
    if auth_session is None:
        return jsonify({"message": "Error, could not identify request id", "status": 400}), 400
    
    identity_id = auth_session.identity_id
    identity = Identity.query.get_or_404(identity_id)
    patient = identity.patient
    practitioner = identity.practitioner
    request_data = auth_session.data.get("request_data", None)
    request_info = Request(
        identity_id=identity.identity_id,
        startedAtTime=datetime.now(),
        description=f'Fetch patient data from {request_data["request_type"]}',
    )
    db.session.add(request_info)
    db.session.flush()
    
    metadata = {}
    #try:
    if request_data["request_type"] == "fitbit":
        fitbit_data = fetch_fitbit_data(patient, request_data)
        data = fitbit_data["data"]
        metadata.update(fitbit_data["metadata"])
    
    request_info.endedAtTime = datetime.now()
    prepared_data = prepare_data(data, request_data, metadata=metadata)
    
    print("data from source: ", data)
    print("prepared data: ", prepared_data)
    print("meta data: ", metadata)

    # verify if data  exists for the given date range
    if all_zeros(prepared_data, "value"):
        return jsonify({
            "message": f"No record found for the specified date range",
            "status": 404
        }), 404

    db.session.commit()
    result = process_and_send_data(identity, prepared_data, request_data, other_data=metadata)
    
    # Change data request status
    data = {"request_data": request_data, "complete": True}
    auth_session.data = data
    db.session.commit()
    print(auth_session.data)
    #except Exception as e:
    #request_info.endedAtTime = datetime.now()
    #db.session.commit()
    #return jsonify({"message": str(e)}), 500
    data_source = "HealthConnect"
    
    if request_data["request_type"] == "fitbit":
        data_source = "Fitbit"
        if request.args.get('from_auth', None):
            return render_template('authorization_granted.html')
    
    # Send access key to patient
    email = request_data.get("meta-data", {}).get("patient", {}).get("email", "")
    org_name = request_data.get("meta-data", {}).get("organization", {}).get("name", "")
    print(email)
    if not send_access_code(email, private_key, org_name, data_source=data_source):
        return jsonify({
            'message': "An error occurred. Email request to patient failed.",
            'status': 500
        }), 500
    return jsonify({
        'message': f"Authorization request/access key sent successfully to {email}.",
        'public_key': auth_session.public_key,
        'status': 200
    }), 200
