from flask import Blueprint, g
from flask import Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from datetime import datetime
ivr = Blueprint('ivr', __name__)

# Global data


def cardio_data_collector():
    heart_rate = g.ses_data["data"].get('heart_rate', None)
    systolic_bp = g.ses_data["data"].get('systolic_blood_pressure', None)
    diastolic_bp = g.ses_data["data"].get('diastolic_blood_pressure', None)
    collection_position = g.ses_data["data"].get('collection_position', None)
    collection_location = g.ses_data["data"].get('collection_location', None)
    collection_person = g.ses_data["data"].get('collection_person', None)
    collection_body_site = g.ses_data["data"].get('collection_body_site', None)

    #print(heart_rate, systolic_bp, diastolic_bp, sep=" ")
    if heart_rate is None:
        with open('standard_responses/heart_rate.xml') as f:
            response = f.read()
        return response
    elif systolic_bp is None:
        with open('standard_responses/systolic_blood_pressure.xml') as f:
            response = f.read()
        return response
    elif diastolic_bp is None:
        with open('standard_responses/diastolic_blood_pressure.xml') as f:
            response = f.read()
        return response
    elif collection_position is None:
        with open('standard_responses/collection_position.xml') as f:
            response = f.read()
        return response
    elif collection_location is None:
        with open('standard_responses/collection_location.xml') as f:
            response = f.read()
        return response
    elif collection_person is None:
        with open('standard_responses/collection_person.xml') as f:
            response = f.read()
        return response
    elif collection_body_site is None:
        with open('standard_responses/collection_body_site.xml') as f:
            response = f.read()
        return response
    else:
        response = '<Response>'
        response += f'<Say>Your provided heartrate is {heart_rate}</Say>'
        response += f'<Say>Your provided systolic blood pressure is {systolic_bp}</Say>'
        response += f'<Say>Your provided diastolic blood pressure is {diastolic_bp}</Say>'
        response += '<GetDigits timeout="30" finishOnKey="#" callbackUrl="https://pghdtofhir.render.com/ivr/submit">'
        response += '<Say>If this is correct and you want to submit, press one followed by the hash sign. If you want to abort press two followed by the hash sign</Say>'
        response += '</GetDigits></Response>'

        return response

def clear_session_data():
    
    g.ses_data["validated"] = False
    g.ses_data["practitioner_id"] = ""
    g.ses_data["patient_id"] = ""
    g.ses_data["data"] = {
        'heart_rate': None,
        'systolic_blood_pressure': None,
        'diastolic_blood_pressure': None,
        'collection_position': None,
        'collection_location': None,
        'collection_person': None,
        'collection_body_site': None
    }
    sessionId = request.values.get('sessionId', None)
    if sessionId:
        session = CallSession.query.filter(CallSession.session_id==sessionId).first()
        if session:
            session.completed_at = datetime.now()
            db.session.commit()

from . import routes

# IVR endpoints
