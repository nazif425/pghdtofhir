import sys, os, random, base64, hashlib, secrets, random, string, requests, uuid, json, smtplib
import fitbit
from urllib.parse import urlencode
from os import environ
from flask import Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
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
        code = data.get("code", None)
        if not code:
            return jsonify({"message": "Invalid payload, access code not provided.", "status": 400}), 400
        auth_session = AuthSession.query.filter_by(state=key).first()
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
        access_code = request.args.get('code', None)
        if not access_code:
            return jsonify({"message": "Invalid request, access code not provided.", "status": 400}), 400
        
        auth_session = AuthSession.query.filter_by(state=access_code).first()
        if auth_session is None:
            return jsonify({"message": "Error, Invalid access code", "status": 403}), 403
        
        patient_id = auth_session.patient_id
        patient = Patient.query.filter_by(patient_id=patient_id).first()
        if patient is None:
            return jsonify({"message": "An error occured, patient does not exist", "status": 500}), 500
        request_data = auth_session.data.get("request_data", None)
        
        print(request_data)
        if not auth_session.data.get("complete", None):
            # fetch data if fitbit token for patient available
            if request_data.get("request_type", None) == "fitbit" and load_tokens_from_db(patient.patient_id):
                return redirect(url_for("wearable.data", code=access_code))
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
        data = request.get_json()
        if not data:
            abort(400, "Invalid request payload")
        
        if data.get("request_type", "") not in ["fitbit", "healthconnect"]:
            abort(400, "Error, request type not provided.")
        
        verify_resources(data)
        instances = get_or_create_instances(data)
        
        patient = instances["patient"]
        practitioner = instances["practitioner"]
        ehr_system = instances["ehr_system"]
        identity = instances["identity"]
        organization = instances["organization"]
        
        # Validate date
        start_date = data["start_date"]
        end_date = data["end_date"]
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
        
        data["start_date"] = start_date
        data["end_date"] = end_date
            
        # map request request data type from unified keys to different sources keys
        if data["request_type"] == "fitbit":
            if data["request_data_type"] == "sleep":
                data["request_data_type"] = "sleepDuration"
            elif data["request_data_type"] == "heart_rate":
                data["request_data_type"] = "restingHeartRate"
        if data["request_type"] == "healthconnect":
            if data["request_data_type"] == "sleep":
                data["request_data_type"] = "SLEEP_SESSION"
            elif data["request_data_type"] == "steps":
                data["request_data_type"] = "STEPS"
            elif data["request_data_type"] == "heart_rate":
                data["request_data_type"] = "HEART_RATE"
        
        access_code = str(generate_unique_5_digit())
        authsession_data = {
            "state": access_code,
            "patient_id": patient.patient_id, 
            "identity_id": identity.identity_id,
            "data": {'request_data': data, "status": "authorization"}
        }

        auth_session = AuthSession(**authsession_data)
        db.session.add(auth_session)
        db.session.commit()
        if data["request_type"] == "fitbit":
            if not send_access_code(patient.email, access_code, practitioner.name, "Fitbit"):
                return jsonify({
                    'message': "An error occurred. Email request to patient failed.",
                    'status': 500
                }), 500
            if not load_tokens_from_db(patient.patient_id):
                auth_link = generate_fitbit_auth_url(auth_session)
                if not send_authorisation_email(patient.email, auth_link, practitioner.name, "Fitbit"):
                    return jsonify({
                        'message': "An error occurred. Email request to patient failed.",
                        'status': 500
                    }), 500
            return jsonify({
                'message': f"Authorization request/access code sent successfully to {patient.email}.",
                'status': 200
            }), 200
            
        
        elif data["request_type"] == "healthconnect":
            if not send_access_code(patient.email, access_code, practitioner.name, "HealthConnect"):
                return jsonify({
                    'message': "An error occurred. Email request to patient failed.",
                    'status': 500
                }), 500
            auth_link = generate_healthconnect_auth_url(auth_session, data)
            if not send_authorisation_email(patient.email, auth_link, practitioner.name, "HealthConnect"):
                return jsonify({
                    'message': "An error occurred. Email request to patient failed.",
                    'status': 500
                }), 500
            return jsonify({
                'message': f"Authorization request/access code sent successfully to {patient.email}.",
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
        abort(404)
    auth_session = AuthSession.query.filter_by(state=state).first()
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
        abort(404)
    if not session.get('patient_id', None):
        query_params = auth_session.data.get('query_params', {})
        session["request_data"] = auth_session.data.get('request_data', None)
        
        return redirect(url_for(
            'wearable.data', 
            code=auth_session.state,
            from_auth=True
        ))
    return redirect(url_for('portal.patient_dashboard'))

@wearable.route('/data', methods=['GET', 'POST'])
def data():
    data = {}
    if request.method == 'GET':
        access_code = request.args.get('code', None)
        if not access_code:
            return jsonify({"message": "Invalid request, access code not provided.", "status": 400}), 400
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
        access_code = metadata.get("user_id", None)
    auth_session = AuthSession.query.filter_by(state=access_code).first()
    if auth_session is None:
        return jsonify({"message": "Error, could not identify request id", "status": 400}), 400
    
    identity_id = auth_session.identity_id
    identity = Identity.query.get_or_404(identity_id)
    patient = identity.patient
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
    prepared_data = prepare_data(data, request_data)
    
    print("data from source: ", data)
    print("prepared data: ", prepared_data)

    if not prepared_data:
        raise Exception("No data found")

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

    if request_data["request_type"] == "fitbit":
        if request.args.get('from_auth', None):
            return render_template('authorization_granted.html')
        return redirect(url_for("wearable.data_request", code=access_code))
    return jsonify({
        'message': "Data successfully fetched and stored",
        'status': 200
    }), 200

@wearable.route('/fetch_fitbit_data', methods=['GET'])
def fetch_fitbit_data2():
    # verify user
    practitioner_id = request.args.get('practitioner_id', session.get('practitioner_id',  None))
    identity_id = request.args.get('id', None)
    identity = Identity.query.get_or_404(identity_id)
    # verify user access
    practitioner = identity.practitioner
    print(practitioner.practitioner_id, practitioner_id, sep=" : ")
    if str(practitioner.practitioner_id) != practitioner_id:
        flash('Sorry, could not authenticate data request.', 'danger')
        return redirect(url_for('portal.practitioner_login'))
    patient = identity.patient
    
    if not session.get('request_data', None):
        return Response("<h1>Sorry, an error occured. Request not found")
    r_data = session["request_data"]
    org = identity.organization
    request_data_type = request.args.get('request_data_type', "steps")
    destination_url = request.args.get('destination_url', None)
    patient_id = patient.patient_id
    token_dict = load_tokens_from_db(patient_id)
    
    request_data = Request(
        identity_id=identity.identity_id,
        startedAtTime=datetime.now(),
        description='Fetch patient data from their fitbit watch',
    )
    db.session.add(request_data)
    db.session.flush()

    # Fetch data
    fitbit_entry = Fitbit.query.filter_by(patient_id=patient_id).first()
    if token_dict:
        fitbit_client = fitbit.Fitbit(CLIENT_ID, CLIENT_SECRET, oauth2=True,
                                    access_token=token_dict['access_token'],
                                    refresh_token=token_dict['refresh_token'],
                                    refresh_cb=lambda t: refresh_and_store_tokens(t, patient_id))
        # fitbit data for a day
        # this_date = datetime.now()
        # fitbit_data = get_fitbit_data(fitbit_client, base_date=this_date)
        
        # fitbit data for a given date range (time series)
        time_series_endpoints = [
            {"url": "sleep", "request_data_type": "sleepDuration"},
            {"url": "activities/tracker/steps", "request_data_type": "steps"},
            {"url": "activities/heart", "request_data_type": "restingHeartRate"},
            {"url": "activities/tracker/calories", "request_data_type": "calories"}
        ]
        today = str(date.today())
        base_date = request.args.get('start_date', today)
        end_date = request.args.get('end_date', today)
        fitbit_time_data = {}
        prepared_data = []
        fitbit_device_info = fitbit_client.get_devices()

        for endpoint in time_series_endpoints:
            if request_data_type == endpoint["request_data_type"]:
                fitbit_time_data.update(get_fitbit_data(
                    fitbit_client,
                    base_date=str(datetime.strptime(base_date, "%Y-%m-%d")),
                    end_date=str(datetime.strptime(end_date, "%Y-%m-%d")),
                    time_series=endpoint["url"]))
        
        if not fitbit_time_data:
            abort(500, "Failed to retrieve Fitbit data")
        
        # prepare data
        if request_data_type == "calories":
            for i in range(len(fitbit_time_data["activities-tracker-calories"])):
                prepared_data.append({
                    "name": "calories",
                    "date": fitbit_time_data["activities-tracker-calories"][i]["dateTime"],
                    "value": fitbit_time_data["activities-tracker-calories"][i]["value"]
                })
        elif request_data_type == "restingHeartRate":
            for i in range(len(fitbit_time_data["activities-heart"])):
                prepared_data.append({
                    "name": "restingHeartRate",
                    "date": fitbit_time_data["activities-heart"][i]["dateTime"],
                    "value": fitbit_time_data["activities-heart"][i]["value"].get("restingHeartRate", 0)
                })
        elif request_data_type == "sleepDuration":
            for i in range(len(fitbit_time_data["sleep"])):
                prepared_data.append({
                    "name": "sleepDuration",
                    "date": fitbit_time_data["sleep"][i]["dateOfSleep"],
                    "value": fitbit_time_data["sleep"][i]["timeInBed"]
                })
        elif request_data_type == "steps":
            for i in range(len(fitbit_time_data["activities-tracker-steps"])):
                prepared_data.append({
                    "name": "steps",
                    "date": fitbit_time_data["activities-tracker-steps"][i]["dateTime"],
                    "value": fitbit_time_data["activities-tracker-steps"][i]["value"]
                })
        #return jsonify(prepared_data)

        request_data.endedAtTime = datetime.now()
        timestamp = request_data.endedAtTime
        db.session.commit()
        
        pghdprovo = Namespace("https://w3id.org/pghdprovo/")
        wearpghdprovo = Namespace("https://w3id.org/wearpghdprovo/")
        prov = Namespace("http://www.w3.org/ns/prov#")
        foaf = Namespace("http://xmlns.com/foaf/0.1/gender")
        
        # Load the RDF graph
        g = Graph()
        g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")
        new_g = Graph()
        other_data = {
            "wearable_name": "FITBIT",
            "wearable_model": fitbit_device_info[0].get("deviceVersion", "") if len(fitbit_device_info) else ""
        }
        new_instances = add_metadata_to_graph(new_g, identity, other_data=other_data)

        category = {
            "Sleep": [],
            "DailyActivity": [],
            "VitalSign": [],
            "Others": [],
        }
        found = False
        # Add data to graph
        for data_set in prepared_data:
            found = True
            declared_data_property = False
            for s, p, o in g.triples((wearpghdprovo[data_set["name"]], RDF.type, OWL.DatatypeProperty)):
                declared_data_property = True
                break

            # Define unique PGHD instance name e.g PGHD.f47ac10b
            instance = unique_id(pghdprovo.PGHD)
            
            # Create an instance
            new_g.add((instance, RDF.type, pghdprovo.PGHD))
            
            # Adding data to instance
            new_g.add((instance, pghdprovo.name, Literal(data_set["name"])))
            new_g.add((instance, pghdprovo.value, Literal(data_set["value"])))
            new_g.add((instance, pghdprovo.dataSource, Literal('Wearable')))
            timestamp = datetime.strptime(data_set["date"], "%Y-%m-%d")
            time_str = timestamp.isoformat(timespec='seconds')
            new_g.add((instance, pghdprovo.hasTimestamp, Literal(time_str, datatype=XSD.dateTime)))
            
            # Add property annotations to instance
            if declared_data_property:
                for annoteProp in [RDFS.label, RDFS.comment, wearpghdprovo.propertySource]:
                    value = g.value(
                        subject=wearpghdprovo[data_set["name"]], 
                        predicate=annoteProp)
                    if value:
                        new_g.add((instance, annoteProp, value))
            
            # Assign patient instance to data
            if new_instances.get("Patient", None):
                new_g.add((instance, prov.wasAttributedTo, new_instances["Patient"]))
            
            # Assign patient instance to data
            if new_instances.get("Patient", None):
                new_g.add((instance, pghdprovo.wasCollectedBy, new_instances["Patient"]))
            
            # Assign patient instance to data
            if new_instances.get("PGHDRequest", None):
                new_g.add((instance, prov.wasGeneratedBy, new_instances["PGHDRequest"]))
            
            # Assign patient instance to data
            if new_instances.get("Wearable", None):
                new_g.add((instance, prov.wasDerivedFrom, new_instances["Wearable"]))
            """
            # Add instance to a data category
            if declared_data_property:
                data_property_class = next(g.objects(wearpghdprovo[data_set["name"]], RDFS.domain))
                if isinstance(data_property_class, URIRef):
                    class_name = get_entity_name(data_property_class)
                    category[class_name].append(instance)
            else:
                category['Others'].append(instance)
            """
        #str_time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        #file_loc = "static/rdf_files/wearpghdprovo_" + str_time + ".ttl"
        triple_store = Graph(store=store)
        
        result = {}
        # Save to remote tripple store
        result["triplestore"] = insert_data_to_triplestore(new_g, store.update_endpoint)
        
        start_date = r_data["start_date"]
        end_date = r_data["end_date"]
        # Validate date
        if not is_timestamp(start_date, format="%Y-%m-%d"):
            start_date = date.today().strftime("%Y-%m-%dT00:00:00")
        else:
            # Convert date to datetime
            start_date = start_date + "T00:00:00"
        r_data["start_date"] = start_date

        if not is_timestamp(end_date, format="%Y-%m-%d"):
            end_date = date.today().strftime("%Y-%m-%dT23:59:59")
        else:
            # Convert date to datetime
            end_date = end_date + "T23:59:59"
        r_data["end_date"] = end_date
        
        # Save to remote fhir server
        if found:
            result["fhir"] = build_fhir_resources(triple_store, r_data)


            if request.args.get('from_auth', None):
                return render_template('authorization_granted.html')
            return jsonify(result)
        abort(404, "No data found")
    else:
        return Response("<h1>Sorry, an error occured.")
