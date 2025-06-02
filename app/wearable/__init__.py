import sys, os, random, base64, hashlib, secrets, random, string, requests, uuid, json, smtplib
import fitbit
from collections import defaultdict
from urllib.parse import urlencode
from os import environ
from flask import Blueprint, Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from fhir.resources.patient import Patient as fhirPatient
from fhir.resources.humanname import HumanName
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace

from ..utils import unique_id, get_entity_name, is_timestamp, get_main_class, add_metadata_to_graph
from ..utils import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, get_timestamps_from_graph, filter_prepared_data
from ..utils import verify_resources, build_fhir_resources, store, insert_data_to_triplestore, reset_query_keys
wearable = Blueprint('wearable', __name__)

def get_fitbit_data(auth2_client, base_date=None, end_date=None, time_series=None):
    if time_series and base_date and end_date:
        step_time_series = auth2_client.time_series(
                time_series, 
                user_id="-", 
                base_date=base_date, 
                end_date=end_date)
        return step_time_series
    elif base_date:
        return {
            'body': auth2_client.body(date=base_date),
            'activities': auth2_client.activities(date=base_date)['summary'],
            'sleep': auth2_client.sleep(date=base_date),
        }
    
def store_tokens_in_db(patient_id, token_dict):
    # Check if the patient already has an entry in the fitbit table
    fitbit_entry = Fitbit.query.filter_by(patient_id=patient_id).first()

    if fitbit_entry:
        # Update the existing entry
        fitbit_entry.access_token = token_dict['access_token']
        fitbit_entry.refresh_token = token_dict['refresh_token']
        fitbit_entry.refresh_time = datetime.utcnow()
    else:
        # Create a new entry
        new_fitbit_entry = Fitbit(
            access_token=token_dict['access_token'],
            refresh_token=token_dict['refresh_token'],
            refresh_time=datetime.utcnow(),
            patient_id=patient_id
        )
        db.session.add(new_fitbit_entry)

    # Commit changes to the database
    db.session.commit()

def load_tokens_from_db(patient_id):
    # Query the fitbit table for the patient
    fitbit_entry = Fitbit.query.filter_by(patient_id=patient_id).first()

    if fitbit_entry:
        return {
            'access_token': fitbit_entry.access_token,
            'refresh_token': fitbit_entry.refresh_token
        }
    else:
        return None

def refresh_and_store_tokens(token, patient_id):
    # Store the new access and refresh tokens in the database
    store_tokens_in_db(patient_id, token)

def generate_fitbit_auth_url(auth_session):
    # Generate a code verifier and code challenge
    code_verifier = ''.join(random.choices(string.ascii_letters + string.digits, k=64))
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip('=')
    
    auth_session.code_verifier = code_verifier
    db.session.commit()
    
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'state': auth_session.private_key,
        'redirect_uri': REDIRECT_URI
    }
    scope = '&scope=activity+cardio_fitness+electrocardiogram+heartrate'\
            '+irregular_rhythm_notifications+location+nutrition'\
            '+oxygen_saturation+profile+respiratory_rate+settings+sleep+social+temperature+weight'
    return "https://www.fitbit.com/oauth2/authorize?" + urlencode(params) + scope

def generate_healthconnect_auth_url(auth_session, request_data):
    private_key = auth_session.private_key
    start_date = request_data["start_date"].split("T")[0]
    end_date = request_data["end_date"].split("T")[0]
    base_url = "https://emr.abdullahikawu.org/deeplink/"
    auth_link = f'{base_url}?id={private_key}&'\
                f'request_data_type={request_data["request_data_type"]}&'\
                f'start_date={start_date}&'\
                f'end_date={end_date}'
    return auth_link

def fetch_fitbit_data(patient, request_data):
    token_dict = load_tokens_from_db(patient.patient_id)
    if not token_dict:
        raise Exception("No Fitbit tokens found for the patient.")

    fitbit_client = fitbit.Fitbit(
        CLIENT_ID, CLIENT_SECRET, oauth2=True,
        access_token=token_dict['access_token'],
        refresh_token=token_dict['refresh_token'],
        refresh_cb=lambda t: refresh_and_store_tokens(t, patient.patient_id)
    )

    time_series_endpoints = [
        {"url": "sleep", "request_data_type": "sleepDuration"},
        {"url": "activities/steps", "request_data_type": "steps"},
        {"url": "activities/heart", "request_data_type": "restingHeartRate"},
        {"url": "activities/calories", "request_data_type": "calories"}
    ]
    base_date = datetime.strptime(request_data["start_date"], "%Y-%m-%dT%H:%M:%S").date()
    end_date = datetime.strptime(request_data["end_date"], "%Y-%m-%dT%H:%M:%S").date()
    fitbit_device_info = fitbit_client.get_devices()
    fitbit_time_data = {}
    for endpoint in time_series_endpoints:
        if request_data["request_data_type"] == endpoint["request_data_type"]:
            fitbit_time_data.update(get_fitbit_data(
                fitbit_client,
                base_date=base_date,
                end_date=end_date,
                time_series=endpoint["url"]))
    
    if not fitbit_time_data:
        raise Exception("Failed to retrieve Fitbit data.")
    metadata = None
    if len(fitbit_device_info):
        metadata = {
            "device_id": fitbit_device_info[0].get("id", ""),
            "wearable_name": "Fitbit",
            "wearable_model": fitbit_device_info[0].get("deviceVersion", "")
        }

    fitbit_data = {
        "data": fitbit_time_data,
        "metadata": metadata
    }

    return fitbit_data

def prepare_data(raw_data, request_data, metadata=None):
    prepared_data = []
    
    def get_data_source(source_names):
        """Helper function to create a unique dataSource string."""
        unique_sources = sorted(set(source_names))  # Ensure uniqueness
        return "healthconnect - " + ", ".join(unique_sources)
    device_id = ""
    if metadata:
        device_id = metadata.get("device_id", "")

    if request_data["request_type"] == "fitbit":
        if request_data["request_data_type"] == "calories":
            for entry in raw_data["activities-calories"]:
                prepared_data.append({
                    "name": "calories",
                    "date": entry["dateTime"],
                    "value": entry["value"],
                    "device_id": device_id,
                    "dataSource": "fitbit"  # Only "fitbit" for fitbit data
                })
        elif request_data["request_data_type"] == "restingHeartRate":
            for entry in raw_data["activities-heart"]:
                prepared_data.append({
                    "name": "restingHeartRate",
                    "date": entry["dateTime"],
                    "value": entry["value"].get("restingHeartRate", 0),
                    "device_id": device_id,
                    "dataSource": "fitbit"  # Only "fitbit" for fitbit data
                })
        elif request_data["request_data_type"] == "sleepDuration":
            for entry in raw_data["sleep"]:
                prepared_data.append({
                    "name": "sleepDuration",
                    "date": entry["dateOfSleep"],
                    "value": entry["timeInBed"],
                    "device_id": device_id,
                    "dataSource": "fitbit"  # Only "fitbit" for fitbit data
                })
        elif request_data["request_data_type"] == "steps":
            for entry in raw_data["activities-steps"]:
                prepared_data.append({
                    "name": "steps",
                    "date": entry["dateTime"],
                    "value": entry["value"],
                    "device_id": device_id,
                    "dataSource": "fitbit"  # Only "fitbit" for fitbit data
                })
    
    elif request_data["request_type"] == "healthconnect":
        # Group data by date
        daily_data = defaultdict(list)
        source_names = defaultdict(list)  # Track source_names for each date
        
        for entry in raw_data["data"]:
            # Extract the date part only
            date = entry["date"].split(" ")[0]
            # Extract the numeric value from the string
            value = int(entry["value"].split(":")[1].strip())
            # Extract the last part of the source_name (e.g., "shealth" from "com.sec.android.app.shealth")
            source_name = entry["source_name"].split(".")[-1]
            
            daily_data[date].append(value)
            source_names[date].append(source_name)  # Track source_names
        
        if request_data["request_data_type"] == "SLEEP_SESSION":
            for date, values in daily_data.items():
                # Sum all sleep durations for the same day
                total_sleep = sum(values)
                # Create a unique dataSource string
                data_source = get_data_source(source_names[date])
                prepared_data.append({
                    "name": "sleepDuration",
                    "date": date,
                    "value": total_sleep,
                    "dataSource": data_source  # e.g., "healthconnect - shealth, fitness"
                })
        elif request_data["request_data_type"] == "STEPS":
            for date, values in daily_data.items():
                # Sum all steps for the same day
                total_steps = sum(values)
                # Create a unique dataSource string
                data_source = get_data_source(source_names[date])
                prepared_data.append({
                    "name": "steps",
                    "date": date,
                    "value": total_steps,
                    "dataSource": data_source  # e.g., "healthconnect - shealth, fitness"
                })
        elif request_data["request_data_type"] == "HEART_RATE":
            for date, values in daily_data.items():
                # Calculate the average heart rate for the same day
                avg_heart_rate = sum(values) / len(values)
                # Create a unique dataSource string
                data_source = get_data_source(source_names[date])
                prepared_data.append({
                    "name": "heart_rate",
                    "date": date,
                    "value": round(avg_heart_rate, 2),  # Round to 2 decimal places
                    "dataSource": data_source  # e.g., "healthconnect - shealth, fitness"
                })
    
    return prepared_data

def process_and_send_data(identity, prepared_data, request_data, other_data=None):
    # Metadata and RDF instance creation
    pghdprovo = Namespace("https://w3id.org/pghdprovo#")
    wearpghdprovo = Namespace("https://w3id.org/wearpghdprovo#")
    prov = Namespace("http://www.w3.org/ns/prov#")
    dc = Namespace("http://purl.org/dc/elements/1.1/")
    result = {}
    
    g = Graph()
    g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")
    new_g = Graph()
    triple_store = Graph(store=store)
    
    reset_query_keys(request_data)
    # Get all timestamps for the given data request
    user_id = request_data["meta-data"]["patient"].get("user_id", None)
    source = request_data['request_type']
    request_data_type = request_data['request_data_type']
    timestamps = get_timestamps_from_graph(triple_store, source, user_id, request_data_type=request_data_type)
    
    # Remove existing data already in triple store
    prepared_data = filter_prepared_data(prepared_data, timestamps, date_key="date")
    if len(prepared_data):
        request_info = Request(
            identity_id=identity.identity_id,
            startedAtTime=datetime.now(),
            description=f'Fetch patient data from {request_data["request_type"]}',
        )
        new_instances = add_metadata_to_graph(new_g, identity, other_data=other_data)

        # Add data to graph
        for data_set in prepared_data:
            instance = unique_id()
            new_g.add((instance, RDF.type, pghdprovo.PGHD))
            new_g.add((instance, RDF.type, pghdprovo.PGHD))
            new_g.add((instance, dc.identifier, Literal(get_entity_name(instance))))
            new_g.add((instance, pghdprovo.name, Literal(data_set["name"])))
            new_g.add((instance, pghdprovo.value, Literal(data_set["value"])))
            new_g.add((instance, pghdprovo.dataSource, Literal(data_set["dataSource"])))
            timestamp = datetime.strptime(data_set["date"], "%Y-%m-%d")
            time_str = timestamp.isoformat(timespec='seconds')
            new_g.add((instance, pghdprovo.hasTimestamp, Literal(time_str, datatype=XSD.dateTime)))

            if new_instances.get("Patient", None):
                new_g.add((instance, prov.wasAttributedTo, new_instances["Patient"]))
                new_g.add((instance, pghdprovo.wasCollectedBy, new_instances["Patient"]))
            if new_instances.get("PGHDRequest", None):
                new_g.add((instance, prov.wasGeneratedBy, new_instances["PGHDRequest"]))
            if new_instances.get("Wearable", None):
                new_g.add((instance, prov.wasDerivedFrom, new_instances["Wearable"]))

            # Add property annotations to instance
            for s, p, o in g.triples((wearpghdprovo[data_set["name"]], RDF.type, OWL.DatatypeProperty)):
                for annoteProp in [RDFS.label, RDFS.comment]:
                    value = g.value(
                        subject=wearpghdprovo[data_set["name"]], 
                        predicate=annoteProp)
                    if value:
                        new_g.add((instance, annoteProp, value))
                break
            if data_set.get("device_id", None):
                new_g.add((instance, pghdprovo.deviceId, Literal(data_set.get("device_id", None))))
        # Save to triplestore
        result["triplestore"] = insert_data_to_triplestore(new_g, store.update_endpoint)
        # Build FHIR resources
        result["fhir"] = build_fhir_resources(new_g, request_data)

    return result

from . import routes

