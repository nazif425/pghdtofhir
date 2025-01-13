import sys, os, random, base64, hashlib, secrets, random, string, requests, uuid, json, smtplib
import fitbit
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

from ..utils import CLIENT_ID, CLIENT_SECRET, redirect_uri

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

def generate_fitbit_auth_url(**kwargs):
    # Generate a code verifier and code challenge
    state = str(uuid.uuid4())
    code_verifier = ''.join(random.choices(string.ascii_letters + string.digits, k=64))
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip('=')
    data = {
        "state": state,
        "code_verifier": code_verifier,
    }
    data.update(kwargs)
    auth_session = AuthSession(**data)
    db.session.add(auth_session)
    db.session.commit()
    
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'state': state,
        'redirect_uri': redirect_uri
    }
    scope = '&scope=activity+cardio_fitness+electrocardiogram+heartrate'\
            '+irregular_rhythm_notifications+location+nutrition'\
            '+oxygen_saturation+profile+respiratory_rate+settings+sleep+social+temperature+weight'
    return "https://www.fitbit.com/oauth2/authorize?" + urlencode(params) + scope

from . import routes

