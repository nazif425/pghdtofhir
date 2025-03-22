import sys, os, random, base64, hashlib, secrets, random, string, requests, uuid, json, smtplib
import fitbit
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlencode
from os import environ
from flask import Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from flask_migrate import Migrate
from sqlalchemy.sql import func
from .models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from .models import Patient, Practitioner, Fitbit, Request, AuthSession
from datetime import date, datetime, timedelta
from rdflib import Graph, URIRef, Literal, XSD, OWL
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace
from SPARQLWrapper import SPARQLWrapper
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore
from fhir.resources.patient import Patient as FhirPatient
from fhir.resources.organization import Organization as FhirOrganization
from fhir.resources.practitioner import Practitioner as FhirPractitioner
from fhir.resources.device import Device
from fhir.resources.encounter import Encounter
from fhir.resources.observation import Observation
from fhir.resources.provenance import Provenance
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.humanname import HumanName
from pydantic import ValidationError
from fhir.resources.coding import Coding
from fhir.resources.period import Period
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
FHIR_SERVER_URL = os.getenv('FHIR_SERVER_URL')
TRIPLESTORE_URL = os.getenv('TRIPLESTORE_URL')

SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_PORT = os.getenv('SMTP_PORT')

# Create triplestore instance
query_endpoint = TRIPLESTORE_URL + "/sparql"
update_endpoint = TRIPLESTORE_URL + "/update"
store = SPARQLUpdateStore(
    query_endpoint=query_endpoint,
    update_endpoint=update_endpoint
)

# RDF Namespaces
pghdprovo = Namespace("https://w3id.org/pghdprovo/")
wearpghdprovo = Namespace("https://w3id.org/wearpghdprovo/")
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

def unique_id(uri_class):
    return URIRef(str(uri_class) + "." + uuid.uuid4().hex[:8])

def get_entity_name(uri):
    entity = str(uri).split('#')[-1]
    entity = entity.split('/')[-1]
    return entity

def is_timestamp(s, format="%Y-%m-%dT%H:%M:%S"):
    s = str(s)
    try:
        datetime.strptime(s, format)
        return True
    except ValueError:
        return False

def get_main_class(graph, subject):
    # Determines the main class of an instance in an RDF graph, considering OWL classes.
    main_class = None
    for obj in graph.objects(subject=subject, predicate=RDF.type):
        # Check if the object is an OWL Class
        if (obj, RDF.type, OWL.Class) in graph:
            if main_class is None:
                main_class = obj
            else:
                # Check if the current class is a subclass of the previous main_class
                if (obj, RDFS.subClassOf, main_class) in graph: 
                    # Corrected: (obj, RDFS.subClassOf, main_class)
                    main_class = obj
    return main_class

def copy_instance(new_g, instance, g, mapping_dict):
    if not mapping_dict.get(str(instance), None):
        # if row.object is not already a copy
        if str(instance) not in [mapping_dict[mapped] for mapped in mapping_dict.keys()]:
            instance_class = get_main_class(g, instance)
            if not instance_class:
                return None
            new_instance = unique_id(instance_class)
            for rdf_type in g.objects(instance, RDF.type):
                new_g.add((new_instance, RDF.type, rdf_type))
            mapping_dict[str(instance)] = str(new_instance)
        else:
            # return as it is a copy of an original instance
            return instance
    return URIRef(mapping_dict[str(instance)])

# This function convert nested key/value structure to a single dimension
# Optional to choose to ignore perperties with list as values 

def transform_data(data, output_data=None, last_path=None, ignore_list=False, sep=":", include=None):
    data_set = {}
    if isinstance(data, dict):
        for key, item in data.items():
            if isinstance(item, str) or isinstance(item, int) or isinstance(item, float):
                if not include:
                    if last_path:
                        output_data[last_path + sep + key] = item
                    else:
                        output_data[key] = item
                elif key == include[0]:
                    data_set['date'] = item
                elif key == include[1]:
                    data_set['value'] = item
            else:
                current_path = last_path + sep + key if last_path else key
                transform_data(data[key], output_data, current_path, 
                        ignore_list=ignore_list, include=include)
    elif isinstance(data, list) and not ignore_list:
        for index, item in enumerate(data):
            if isinstance(item, str) or isinstance(item, int) or isinstance(item, float):
                if not include or key in include:
                    if last_path:
                        output_data[last_path + sep + str(index)] = item
                    else:
                        output_data[str(index)] = item
                elif key == include[0]:
                    data_set['date'] = item
                elif key == include[1]:
                    data_set['value'] = item
            elif isinstance(item, dict):
                current_path = last_path + sep + str(index)
                transform_data( data[index], output_data, current_path, 
                        ignore_list=ignore_list, include=include)
    if data_set:
        output_data.append(data_set)
def send_access_code(receiver_email, access_code, name="", data_source="Fitbit"):
    sender_email = SENDER_EMAIL
    smtp_server = SMTP_SERVER
    password = SMTP_PASSWORD
    smtp_port = SMTP_PORT

    # Email template
    email_template = """
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 10px; background-color: #f9fafc;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 5px;">
        <h2 style="color: #2c3e50; text-align: center;">Healthcare Data Authorization</h2>
        <p><strong>Dear Patient,</strong></p>
        <p>A healthcare provider at {name} has requested for access to your {data_source} data.</p>
        <p>The code below, if shared, enables access to your data from {data_source}. Ignore or do not share unless informed or in alignment with this. Otherwise, consult your healthcare professional.</p>
        <p style="text-align: center; margin: 20px 0;">
            <div
            style="background-color: #0078d7; color: #ffffff; text-decoration: none; padding: 10px 20px; border-radius: 5px; display: inline-block;">
            {access_code}
            </div>
        </p>
        <p style="text-align: center; font-size: 10px; color: #888888; margin-top: 20px; border-top: 1px solid #eeeeee; padding-top: 10px;">
            This is an automated message. Please do not reply.
        </p>
        </div>
    </body>
    </html>
    """

    # Format the email body with dynamic content
    body = email_template.format(
        data_source=data_source,
        name=name,
        access_code=access_code
    )

    # Create the email
    message = MIMEMultipart()
    message["From"] = f"Healthcare Provider <{sender_email}>"
    message["To"] = receiver_email
    message["Subject"] = f"Healthcare Data Authorization Code"
    message.attach(MIMEText(body, "html"))

    try:
        # Connect to the server using SSL
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, password)  # Login
            server.sendmail(sender_email, receiver_email, message.as_string())  # Send email
        print("Email sent successfully!")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_authorisation_email(receiver_email, auth_link, name="", data_source="Fitbit"):
    sender_email = SENDER_EMAIL
    smtp_server = SMTP_SERVER
    password = SMTP_PASSWORD
    smtp_port = SMTP_PORT

    # Email template
    email_template = """
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 10px; background-color: #f9fafc;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 5px;">
        <h2 style="color: #2c3e50; text-align: center;">Healthcare Data Authorization</h2>
        <p><strong>Dear Patient,</strong></p>
        <p>Please click the button below to authorize access to your {data_source} data for your healthcare provider at {name}.</p>
        <p style="text-align: center; margin: 20px 0;">
            <a href="{auth_link}" 
            style="background-color: #0078d7; color: #ffffff; text-decoration: none; padding: 10px 20px; border-radius: 5px; display: inline-block;">
            Authorize Access
            </a>
        </p>
        <p style="font-size: 12px; color: #555555; margin-top: 20px;">
            <em>Note:</em> By authorizing access to your {data_source} data, you consent to its use for clinical decision-making and research.
            {revoke_note}
        </p>
        <p style="text-align: center; font-size: 10px; color: #888888; margin-top: 20px; border-top: 1px solid #eeeeee; padding-top: 10px;">
            This is an automated message. Please do not reply.
        </p>
        </div>
    </body>
    </html>
    """

    # Add revoke note only for Fitbit
    revoke_note = (
        "You can revoke this access anytime from your Fitbit account." 
        if data_source == "Fitbit" 
        else ""
    )

    # Format the email body with dynamic content
    body = email_template.format(
        data_source=data_source,
        name=name,
        auth_link=auth_link,
        revoke_note=revoke_note
    )

    # Create the email
    message = MIMEMultipart()
    message["From"] = f"Healthcare Provider <{sender_email}>"
    message["To"] = receiver_email
    message["Subject"] = f"Authorize {data_source} Data Access"
    message.attach(MIMEText(body, "html"))

    try:
        # Connect to the server using SSL
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, password)  # Login
            server.sendmail(sender_email, receiver_email, message.as_string())  # Send email
        print("Email sent successfully!")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def add_metadata_to_graph(new_g, identity, other_data=None):
    wearable_name = ""
    if other_data:
        wearable_name = other_data.get("wearable_name", "")
        wearable_model = other_data.get("wearable_model", "")
    # add a instance
    # g.add((subject, predicate, object))

    g = Graph()
    g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")

    meta_data = {
        "pghdprovo:Patient":{
            "givenName": identity.patient.name,
            "birthday":identity.patient.birthday,
            "gender":identity.patient.gender,
            "userid":identity.patient.user_id,
            "phoneNumber":identity.patient.phone_number,
            "address":identity.patient.address
        },
        "pghdprovo:Practitioner":{
            "givenName":identity.practitioner.name,
            "birthday":identity.practitioner.birthday,
            "gender":identity.practitioner.gender,
            "userid": identity.practitioner.user_id,
            "phoneNumber": identity.practitioner.phone_number,
            "address":identity.practitioner.address,
            "role":identity.practitioner.role
        },
        "prov:Organization":{
            "orgAddress": identity.organization.address,
            "orgEmail": identity.organization.email,
            "orgId": identity.organization.org_id,
            "orgName": identity.organization.name,
        },
        "pghdprovo:PGHDRequest":{
            "requestId": identity.request.request_id,
            "startedAtTime": identity.request.startedAtTime.strftime("%Y-%m-%dT%H:%M:%S"),
            "endedAtTime": identity.request.endedAtTime.strftime("%Y-%m-%dT%H:%M:%S"),
            "description": identity.request.description,
        },
        "pghdprovo:Application": {
            "appName": identity.ehr_system.name
        }
    }
    if wearable_name:
        meta_data.update({
            "s4wear:Wearable": {
                "deviceName": wearable_name,
                "deviceModel": wearable_model
            }
        })
    #print(meta_data)
    #print(fitbit_time_data)
    mapping_dict = {}

    # Add metadata to graph
    for data_class, data in meta_data.items():
        # Iterate over the properties of the each class
        query = """
        SELECT ?subject ?property ?object
        WHERE {
            ?subject a """ + data_class + """.
            ?subject ?property ?object .
            ?subject a ?type .
            FILTER (?type != owl:NamedIndividual).
            OPTIONAL {
                ?object a ?objectType .
                FILTER (?objectType != owl:NamedIndividual).
            }
        }"""
        result = g.query(query_header + query)
        
        # create new copy of the existing instances in the template and add data to it 
        for row in result:
            new_subject = copy_instance(new_g, row.subject, g, mapping_dict)
            # print(str(row.subject), str(new_subject), sep=" : ")

            # if object is an individual
            if isinstance(row.object, URIRef):
                if OWL.Class not in list(g.objects(row.object, RDF.type)):
                    new_object = copy_instance(new_g, row.object, g, mapping_dict)
                    if new_object:
                        # print(str(row.object), str(new_object), sep=" : ")
                        new_g.add((new_subject, row.property, new_object))
            else:
                # get property name from URI
                row_property = get_entity_name(row.property)
                # add data that match property name
                if data.get(row_property, None):
                    if is_timestamp(data[row_property]):
                        new_g.add((new_subject, row.property, Literal(data[row_property], datatype=XSD.dateTime)))
                    else:
                        new_g.add((new_subject, row.property, Literal(data[row_property])))
    
    # Find new copy of instances from earlier defined
    new_instances = {}
    for old_instance in mapping_dict.keys():
        instance_class = get_main_class(g, URIRef(old_instance))
        if instance_class:
            class_name = get_entity_name(instance_class)
            new_instances[class_name] = URIRef(mapping_dict[old_instance])
    return new_instances


def check_resource_existence(resource_type, identifier, system=None):
    """
    Check if a FHIR resource exists on the server.
    :param resource_type: The type of the FHIR resource (e.g., Patient, Practitioner).
    :param identifier: The identifier of the resource to search for.
    :param system: (Optional) The system namespace of the identifier.
    :return: True if resource exists, False otherwise.
    """
    search_params = {"identifier": f"{system}|{identifier}" if system else identifier}
    response = requests.get(f"{FHIR_SERVER_URL}/{resource_type}", params=search_params)
    
    if response.status_code != 200:
        abort(500, f"Error querying {resource_type} resource: {response.text}")
    
    resources = response.json().get("entry", [])
    return len(resources) > 0

def create_practitioner(request_data):
    server_url = FHIR_SERVER_URL
    """
    Create a Practitioner resource from request_data and send it to the FHIR server.
    
    Args:
        request_data (dict): The request data containing meta-data with practitioner info.
        server_url (str, optional): The base URL of the HAPI FHIR server. Defaults to public server.
    
    Returns:
        str or None: The identifier value (e.g., "9d121eab-f9a6-44f6-92af-4352c932d2da") if successful,
                     None if creation fails.
    """
    try:
        # Extract practitioner data from meta-data
        practitioner_info = request_data.get("meta-data", {}).get("practitioner", {})
        if not practitioner_info:
            print("Error: No practitioner data found in request")
            return None

        # Parse name into given and family (assuming "given family" format)
        full_name = practitioner_info.get("name", "").split()
        given_name = full_name[0] if full_name else "Unknown"
        family_name = " ".join(full_name[1:]) if len(full_name) > 1 else "Unknown"

        # Create Practitioner resource with explicit keyword arguments using practitioner_info only
        practitioner_resource = FhirPractitioner(
            id=practitioner_info.get("user_id"),
            identifier=[
                {
                    "system": "urn:uuid",
                    "value": practitioner_info.get("user_id")
                }
            ],
            active=True,
            name=[
                {
                    "use": "official",
                    "family": family_name,
                    "given": [given_name]
                }
            ],
            telecom=[
                {
                    "system": "phone",
                    "value": practitioner_info.get("phone_number")
                }
            ] if practitioner_info.get("phone_number") else [],
            gender=practitioner_info.get("gender").lower() if practitioner_info.get("gender", None) else None,
            birthDate=practitioner_info.get("birthdate", None)  # Assumes YYYY-MM-DD format
        )

        # Send to FHIR server
        headers = {"Content-Type": "application/fhir+json"}
        response = requests.post(
            f"{server_url}/Practitioner",
            data=practitioner_resource.json(),
            headers=headers
        )

        # Check response
        if response.status_code == 201:
            identifier_value = practitioner_info.get("user_id")
            print(f"Practitioner created successfully with ID: {identifier_value}")
            return identifier_value
        else:
            print(f"Error: Failed to create Practitioner. Status: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

def create_patient(request_data):
    server_url = FHIR_SERVER_URL  # Assumes FHIR_SERVER_URL is defined elsewhere
    """
    Create a Patient resource from request_data and send it to the FHIR server.
    
    Args:
        request_data (dict): The request data containing meta-data with patient info.
    
    Returns:
        str or None: The identifier value (e.g., "1231") if successful, None if creation fails.
    """
    try:
        # Extract patient data from meta-data
        patient_info = request_data.get("meta-data", {}).get("patient", {})
        if not patient_info:
            print("Error: No patient data found in request")
            return None

        # Parse name into given and family (assuming "given family" format)
        full_name = patient_info.get("name", "").split()
        given_name = full_name[0] if full_name else "Unknown"
        family_name = " ".join(full_name[1:]) if len(full_name) > 1 else "Unknown"

        # Create Patient resource with explicit keyword arguments using patient_info only
        patient_resource = FhirPatient(
            id=patient_info.get("user_id"),
            identifier=[
                {
                    "system": "urn:uuid",
                    "value": patient_info.get("user_id")
                }
            ],
            active=True,
            name=[
                {
                    "use": "official",
                    "family": family_name,
                    "given": [given_name]
                }
            ],
            telecom=[
                {
                    "system": "phone",
                    "value": patient_info.get("phone_number")
                }
            ] if patient_info.get("phone_number") else [] +
            [
                {
                    "system": "email",
                    "value": patient_info.get("email")
                }
            ] if patient_info.get("email") else [],
            gender=patient_info.get("gender").lower() if patient_info.get("gender", None) else None,
            birthDate=patient_info.get("birthdate", None)  # Assumes YYYY-MM-DD or will need conversion
        )

        # Send to FHIR server
        headers = {"Content-Type": "application/fhir+json"}
        response = requests.post(
            f"{server_url}/Patient",
            data=patient_resource.json(),
            headers=headers
        )

        # Check response
        if response.status_code == 201:
            identifier_value = patient_info.get("user_id")
            print(f"Patient created successfully with ID: {identifier_value}")
            return identifier_value
        else:
            print(f"Error: Failed to create Patient. Status: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

def create_organization(request_data):
    server_url = FHIR_SERVER_URL  # Assumes FHIR_SERVER_URL is defined elsewhere
    """
    Create an Organization resource from request_data and send it to the FHIR server.
    
    Args:
        request_data (dict): The request data containing meta-data with organization info.
    
    Returns:
        str or None: The identifier value (e.g., "7477d1df-59af-4a47-b6fb-0ea842dcc0fd") if successful,
                     None if creation fails.
    """
    try:
        # Extract organization data from meta-data
        org_info = request_data.get("meta-data", {}).get("organization", {})
        if not org_info:
            print("Error: No organization data found in request")
            return None

        # Create Organization resource with explicit keyword arguments
        organization_resource = FhirOrganization(
            id=org_info.get("org_id"),
            identifier=[
                {
                    "system": "urn:uuid",
                    "value": org_info.get("org_id")
                }
            ],
            name=org_info.get("name"),
        )

        # Send to FHIR server
        headers = {"Content-Type": "application/fhir+json"}
        response = requests.post(
            f"{server_url}/Organization",
            data=organization_resource.json(),
            headers=headers
        )

        # Check response
        if response.status_code == 201:
            identifier_value = org_info.get("org_id")
            print(f"Organization created successfully with ID: {identifier_value}")
            return identifier_value
        else:
            print(f"Error: Failed to create Organization. Status: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

def verify_resources(data):
    """
    Verifies the existence of Patient, Practitioner, Encounter, and Organization resources.
    """

    # Check patient email
    patient_email = data["meta-data"]["patient"].get("email", None)
    if not patient_email:
        abort(400, "Error, patient email not provided.")

    # find patient number
    if "IVR" in data["request_type"]:
        patient_phone_number = data["meta-data"]["patient"].get("phone_number", None)
        if not patient_phone_number:
            abort(400, "Error, patient number not provided.")
    
    # FHIR Resources verification
    patient_user_id = data["meta-data"]["patient"].get("user_id", None)
    if not patient_user_id:
        abort(400, "Error, patient user_id not provided.")
    if not check_resource_existence("Patient", patient_user_id):
        if not create_patient(data):
            abort(500, f"Failed to create Patient with ID '{patient_user_id}'.")

    practitioner_user_id = data["meta-data"]["practitioner"].get("user_id", None)
    if not practitioner_user_id:
        abort(400, "Error, practitioner user_id not provided.")
    if not check_resource_existence("Practitioner", practitioner_user_id):
        if not create_practitioner(data):
            abort(500, f"Failed to create Practitioner with ID '{practitioner_user_id}'.")

    organization_user_id = data["meta-data"]["organization"].get("org_id", None)
    if not organization_user_id:
        abort(400, "Error, organization user_id not provided.")
    if not check_resource_existence("Organization", organization_user_id):
        if not create_organization(data):
            abort(500, f"Failed to create Organization with ID '{organization_user_id}'.")
    
    return True

# find record of the request meta-data on the database and create new record if no record found
def get_or_create_instances(data):

    patient = data["meta-data"]["patient"]
    patient_user_id = patient.get("user_id", None)
    patient_email = patient.get("email", None)
    patient_phone_number = patient.get("phone_number", None)
    practitioner_user_id = data["meta-data"]["practitioner"].get("user_id", None)
    
    # find patient in database
    patient = Patient.query.filter_by(user_id=patient_user_id).first()
    if patient is None:
        patient = Patient(
                name=data["meta-data"]["patient"].get("name", ""),
                user_id=patient_user_id, 
                phone_number=data["meta-data"]["patient"].get("phone_number", ""),
                birthday=data["meta-data"]["patient"].get("birthday", ""),
                gender=data["meta-data"]["patient"].get("gender", ""),
                address=data["meta-data"]["patient"].get("address", ""),
                email=patient_email) # No name for now
        db.session.add(patient)
        db.session.flush() # To get the patient_id
        
    # check if practitioner exists
    practitioner = Practitioner.query.filter_by(user_id=practitioner_user_id).first()
    if practitioner is None:
        practitioner = Practitioner(
                name=data["meta-data"]["practitioner"].get("name", ""),
                user_id=practitioner_user_id,
                phone_number=data["meta-data"]["practitioner"].get("phone_number", ""),
                birthday=data["meta-data"]["practitioner"].get("birthday", ""),
                address=data["meta-data"]["practitioner"].get("address", ""),
                gender=data["meta-data"]["practitioner"].get("gender", ""),
                role=data["meta-data"]["practitioner"].get("role", ""),
                email=data["meta-data"]["practitioner"].get("email", ""))
        db.session.add(practitioner)
        db.session.flush()
    
    ehr_system = EHRSystem.query.filter_by(
            name=data["meta-data"]["application"].get("name", "")).first()
    if ehr_system is None:
        ehr_system = EHRSystem(
                name=data["meta-data"]["application"].get("name", ""))
        db.session.add(ehr_system)
        db.session.flush()

    organization = Organization.query.filter_by(
            org_id=data["meta-data"]["organization"].get("org_id", "")).first()
    if organization is None:
        organization = Organization(
                name=data["meta-data"]["organization"].get("name", ""),
                org_id=data["meta-data"]["organization"].get("org_id", ""),
                email=data["meta-data"]["organization"].get("email", ""),
                address=data["meta-data"]["organization"].get("address", ""))
        db.session.add(organization)
        db.session.flush()
    
    identity = Identity.query.filter_by(
            patient_id=patient.patient_id, 
            practitioner_id=practitioner.practitioner_id).first()
    if identity is None:
        identity = Identity(
                organization_id=organization.organization_id,
                ehr_system_id=ehr_system.ehr_system_id,
                patient_id=patient.patient_id, 
                practitioner_id=practitioner.practitioner_id)
        db.session.add(identity)
        db.session.flush()
    db.session.commit()
    
    return {
        "patient": patient,
        "practitioner": practitioner,
        "ehr_system": ehr_system,
        "identity": identity,
        "organization": organization
    }

def build_fhir_resources(g, request_data):
    start_date = request_data.get("start_date", None)
    end_date = request_data.get("end_date", None)
    request_type = request_data.get("request_type", None)
    request_data_type = request_data.get("request_data_type", None)
    patient_id = request_data["meta-data"]["patient"]["user_id"]
    practitioner_id = request_data["meta-data"]["practitioner"]["user_id"]
    organization_id = request_data["meta-data"]["organization"].get("org_id", None)
    organization_id = f"Organization?identifier={organization_id}"
    encounter_id = request_data.get("encounter", None)
    organization = None
    encounter = None
    device = None
    
    
    # create encounter resource
    encounter_id = "urn:uuid:encounter-1"
    try:
        encounter = Encounter(
            id="encounter-1",
            status="finished",
            class_fhir=[{
                "coding": [{
                    "code":"AMB",
                    "display":"Ambulatory",
                    "system":"http://terminology.hl7.org/CodeSystem/v3-ActCode"
                }]
            }],
            identifier=[
                {
                    "system": "urn:uuid",
                    "value": str(uuid.uuid4())
                }
            ],
            subject={"reference": f"Patient?identifier={patient_id}"},
            participant=[{
                "actor": {"reference": f"Practitioner?identifier={practitioner_id}"},
                "period": {
                    "start": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                }
            }],
            serviceProvider={"reference": organization_id},
        )
    except ValueError as e:
        print("Encounter error: ", e.errors())
    
    # create device resource
    if request_type == "fitbit":
        try:
            device = Device(
                id="device-1",
                identifier=[
                    {
                        "system": "urn:uuid",
                        "value": str(uuid.uuid4())
                    }
                ],
                type=[{
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "49062001",
                            "display": "Device"
                        }
                    ]
                }],
                manufacturer=None,
                modelNumber=None,
                owner={"reference": f"Patient?identifier={patient_id}"}
            )
        except ValueError as e:
            print("Device error: ", e.errors())

    
    
    # Load the JSON data into a Python dictionary
    with open('templates/category_template.json', 'r') as file:
        categories = json.load(file)
    with open('templates/code_template.json', 'r') as file:
        codings = json.load(file)
    with open('templates/quantityvalue_template.json', 'r') as file:
        value_quantities = json.load(file)
    
    categories_list = {
        "vital-signs": ["diastolic_blood_pressure", "systolic_blood_pressure", "heart_rate", "restingHeartRate"],
        "activity": ["steps", "sleepDuration", "calories"]
    }
    
    triple_store = Graph(store=store)
    # triple_store_loc = "static/rdf_files/wearpghdprovo-onto-store.ttl"
    # triple_store.parse(triple_store_loc, format="turtle")
    query = generate_sparql_query(request_data)
    
    result = triple_store.query(query)
    bodysite_coding_key = None
    bodysite_coding = None
    deviceName = None
    deviceModel = None
    counter = 0
    observations = []
    for record in result:
        counter += 1
        if record.name.value in categories_list["vital-signs"]:
            category = categories["vital-signs"]
        else:
            category = categories["activity"]

        value_set = value_quantities[record.name.value]
        value_set["value"] = record.value.value
        if record.get("bodysite", None):
            bodysite_coding_key = "left_arm" if record.bodysite.value == "Left arm" else "right_arm"
            bodysite_coding = codings.get(bodysite_coding_key, None)
        if record.get("deviceName", None):
            deviceName = record.deviceName.value
        if record.get("deviceModel", None):
            deviceModel = record.deviceModel.value
        extensions = []
        extensions.append({
            "url": "http://hl7.org/fhir/StructureDefinition/observation-provenance",
            "valueReference": {
                "reference": "urn:uuid:provenance-1",
                "display": "Provenance for PGHD"
            }
        })
        if record.get("posture", None):
            print(record.get("posture", None))
            posture_key = record["posture"].value.lower()
            print(posture_key)
            posture_coding = codings.get(posture_key, None)
            extensions.append({
                "url": "https://w3id.org/pghdprovo/posture",
                "valueCodeableConcept": {
                    "coding": [posture_coding]
                }
            })
        if record.get("location", None):
            location_key = record["location"].value.lower()
            location_coding = codings.get(location_key, None)
            extensions.append({
                "url": "https://w3id.org/pghdprovo/locationOfPatient",
                "valueCodeableConcept": {
                    "coding": [location_coding]
                }
            })
        print(extensions)
        # create observation resources
        try:
            observations.append(Observation(
                id=f"observation-{counter}",
                status="final",
                identifier=[
                    {
                        "system": "urn:uuid",
                        "value": str(uuid.uuid4())
                    }
                ],
                category=category,
                code={
                    "coding": [
                        codings[record.name.value]
                    ]
                },
                bodySite={"coding": [bodysite_coding]} if bodysite_coding else None,
                subject={"reference": f"Patient?identifier={patient_id}"},
                encounter={"reference": encounter_id},
                device={"reference": "urn:uuid:device-1"} if device else None,
                valueQuantity=value_set,
                effectiveDateTime=(record.timestamp.value).strftime("%Y-%m-%dT%H:%M:%SZ"),
                extension=extensions
            ))
        except ValueError as e:
            print("observation error: ", e.errors())
    now = datetime.now().isoformat() + 'Z'
    
    # Create Provenance resource
    provenance = None
    try:
        provenance = Provenance(
            id="prov1",
            target=[{"reference": f"urn:uuid:observation-{i+1}"} for i in range(counter)],
            recorded=now,  # Commented out as per your example
            agent=[{
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                            "code": "author",
                            "display": "Author"
                        }
                    ]
                },
                "who": {"reference": f"Practitioner?identifier={practitioner_id}"},
                "onBehalfOf": {"reference": organization_id}
            }],
            entity=[{
                "role": "source",
                "what": {
                    "reference": "urn:uuid:device-1" 
                } 
            }] if device else None,
            encounter={
                "reference": "urn:uuid:encounter-1",
                "display": "Patient encounter for PGHD record"
            }
        )
    except ValueError as e:
        print("Provenance error: ", e.errors())
    # Bundle all resources
    bundle = Bundle(
        type="transaction",
        entry=[]
    )

    # Add Observation resources to the bundle
    for i, observation in enumerate(observations):
        bundle.entry.append(BundleEntry(
            resource=observation,
            request={
                "method": "POST",
                "url": "Observation"
            },
            fullUrl=f"urn:uuid:observation-{i+1}"
        ))

    # Add Provenance resource to the bundle
    bundle.entry.append(BundleEntry(
        resource=provenance,
        request={
            "method": "POST",
            "url": "Provenance"
        },
        fullUrl=f"urn:uuid:provenance-1"
    ))

    # Add Device resource (if defined)
    if device:
        device.manufacturer = deviceName
        device.modelNumber = deviceModel
        bundle.entry.append(BundleEntry(
            resource=device,
            request={
                "method": "POST",
                "url": "Device"
            },
            fullUrl=f"urn:uuid:device-1"
        ))

    # Add Encounter resource (if defined)
    if encounter:
        bundle.entry.append(BundleEntry(
            resource=encounter,
            request={
                "method": "POST",
                "url": "Encounter"
            },
            fullUrl=encounter_id
        ))
    # Serialize the bundle to JSON
    bundle_json = bundle.json(indent=2)

    # Headers
    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json"
    }

    # Send the bundle via POST
    response = requests.post(FHIR_SERVER_URL, headers=headers, data=bundle_json)

    # Print response
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    return response.json()

def insert_data_to_triplestore(graph, update_endpoint=update_endpoint):
    """
    Insert RDF triples from a graph into a SPARQL endpoint.

    Parameters:
    - new_g (rdflib.Graph): The RDF graph containing the data to be inserted.
    - update_endpoint (str): URL of the SPARQL update endpoint.

    Returns:
    - str: The response from the SPARQL endpoint.

    Raises:
    - Exception: If the SPARQL query fails or the response indicates an error.
    """
    # Create a SPARQLWrapper object
    sparql = SPARQLWrapper(update_endpoint)

    # Serialize the graph to N-Triples
    ntriples_data = graph.serialize(format='nt')

    # Define the SPARQL INSERT query
    insert_query = f"""
        INSERT DATA {{
            {ntriples_data}
        }}
    """

    # Set the query and execute it
    sparql.setQuery(insert_query)
    sparql.setMethod('POST')  # Use POST for updates
    try:
        response = sparql.query()
        
        # Check if the operation was successful
        if response.response.status == 200:
            print("Triples inserted successfully!")
            return response.response.read().decode('utf-8')
        else:
            print(f"Failed to insert triples. Status code: {response.response.status}")
            return f"Error: {response.response.read().decode('utf-8')}"
    except Exception as e:
        return f"An error occurred during the SPARQL update: {str(e)}"

def generate_sparql_query(request_data):
    # Extract necessary information from the request data
    request_type = request_data.get("request_type", "")
    request_data_type = request_data.get("request_data_type", "")
    start_date = request_data.get("start_date", "")
    end_date = request_data.get("end_date", "")
    patient_id = request_data.get("meta-data", {}).get("patient", {}).get("user_id", "")
    # convert request data type to the standard keywords recorded
    if request_data["request_type"] == "healthconnect":
        if request_data["request_data_type"] == "SLEEP_SESSION":
            request_data["request_data_type"] = "sleepDuration"
        elif request_data["request_data_type"] == "STEPS":
            request_data["request_data_type"] = "steps"
        elif request_data["request_data_type"] == "HEART_RATE":
            request_data["request_data_type"] = "heart_rate"
    fitbit_vars = ""
    if request_data["request_type"] == "fitbit":
        fitbit_vars = "?deviceName ?deviceModel"
    # Construct the SPARQL query dynamically
    query = f"""
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
    SELECT ?subject ?name ?value ?source ?timestamp ?description ?label ?posture ?bodysite ?location ?deviceid ?deviceName ?deviceModel {fitbit_vars}
    WHERE {{
        ?subject a pghdprovo:PGHD .
        ?subject pghdprovo:name ?name .
        ?subject pghdprovo:value ?value .
        ?subject pghdprovo:dataSource ?source .
        ?subject pghdprovo:hasTimestamp ?timestamp .
        FILTER (?timestamp >= "{start_date}"^^xsd:dateTime && ?timestamp <= "{end_date}"^^xsd:dateTime) .
        FILTER (STRSTARTS(?source, "{request_type}")) .
        FILTER (?name = "{request_data_type}") .
        ?subject prov:wasAttributedTo ?patient .
        ?patient pghdprovo:userid ?userid .
        FILTER (?userid = "{patient_id}") .
        OPTIONAL {{?subject rdfs:comment ?description .}}
        OPTIONAL {{?subject rdfs:label ?label .}}
        OPTIONAL {{?subject pghdprovo:deviceId ?deviceid .}}
        OPTIONAL {{
            ?subject pghdprovo:hasContextualInfo ?state .
            ?state a pghdprovo:State .
            ?state pghdprovo:posture ?posture .
        }}
        OPTIONAL {{
            ?subject pghdprovo:hasContextualInfo ?protocol .
            ?protocol a pghdprovo:Protocol .
            ?protocol pghdprovo:bodySite ?bodysite .
        }}
        OPTIONAL {{
            ?subject pghdprovo:hasContextualInfo ?contextualinfo .
            ?contextualinfo a pghdprovo:ContextualInfo .
            ?contextualinfo pghdprovo:locationOfPatient ?location .
        }}
        OPTIONAL {{
            ?subject prov:wasDerivedFrom ?Wearable .
            ?Wearable pghdprovo:deviceName ?deviceName .
        }}
        OPTIONAL {{
            ?subject prov:wasDerivedFrom ?Wearable .
            ?Wearable pghdprovo:deviceModel ?deviceModel .
        }}
    }}
    """
    return query

def transform_query_result(query_result):
    # Transform the query result into the desired array format
    records = []
    for result in query_result:
        name = result.name.value
        if name == "sleepDuration":
            name = "sleep"
        elif name in ["heart_rate", "restingHeartRate"]:
            name = "heartrate"
        record = {
            "name": name,
            "date": result.timestamp.value.strftime("%Y-%m-%d"),
            "value": result.value.value,
            "device_id": result.get("deviceid").value if result.get("deviceid") else "",
            "dataSource": result.source.value
        }
        if "IVR" in record.get("dataSource", None):
            record.update({
                "metadata": {
                    "posture": result.get("posture").value if result.get("posture") else "",
                    "bodysite": result.get("bodysite").value if result.get("bodysite") else "",
                    "location": result.get("location").value if result.get("location") else ""
                }
            })
        records.append(record)
    return records

def generate_unique_5_digit(storage_file="used_numbers.txt"):
    # Load used numbers from file
    try:
        with open(storage_file, "r") as file:
            used_numbers = set(file.read().splitlines())
    except FileNotFoundError:
        used_numbers = set()

    # Generate a unique number
    while True:
        number = random.randint(10000, 99999)
        if str(number) not in used_numbers:
            used_numbers.add(str(number))
            # Save the updated list of used numbers
            with open(storage_file, "w") as file:
                file.write("\n".join(used_numbers))
            return number

def get_timestamps_from_graph(graph, source, patient_id, request_data_type=None):
    """
    Retrieve timestamps from the RDF graph based on source, patient_id, and optionally request_data_type.

    Args:
        graph: The RDFlib graph instance.
        source: The data source to filter by.
        patient_id: The patient ID to filter by.
        request_data_type: The name filter for the data type. Defaults to None.

    Returns:
        A list of timestamps as strings.
    """
    # Prepare the SPARQL query
    query_template = """
    PREFIX pghdprovo: <https://w3id.org/pghdprovo/>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    
    SELECT ?timestamp WHERE {
        ?subject pghdprovo:hasTimestamp ?timestamp .
        ?subject pghdprovo:dataSource ?source .
        ?subject prov:wasAttributedTo ?patient .
        ?patient pghdprovo:userid ?userid .
        
        FILTER (STRSTARTS(?source, ?src))
        FILTER (?userid = ?pid)
        {optional_name_filter}
    }
    """

    # Add optional name filter if request_data_type is provided
    if request_data_type:
        optional_name_filter = "FILTER (?name = ?data_type)"
        query_template = query_template.replace("{optional_name_filter}", optional_name_filter)
    else:
        query_template = query_template.replace("{optional_name_filter}", "")

    # Prepare the query
    prepared_query = prepareQuery(query_template)

    # Execute the query with bindings
    bindings = {
        "src": source,
        "pid": patient_id,
    }
    if request_data_type:
        bindings["data_type"] = request_data_type

    result = graph.query(prepared_query, initBindings=bindings)

    # Extract timestamps from the result
    timestamps = [str(row.timestamp) for row in result]
    return timestamps

def filter_prepared_data(prepared_data, timestamps, date_key="timestamp"):
    """
    Filter prepared_data to exclude entries with timestamps that exist in the provided timestamps array.

    Args:
        prepared_data: The prepared data to filter.
        timestamps: The list of timestamps in "YYYY-MM-DDTHH:MM:SS" format.
        date_key: The key in the session dictionary where the date is stored. Defaults to "timestamp".

    Returns:
        The filtered prepared_data array.
    """
    # Parse timestamps into datetime objects for comparison
    existing_timestamps = {datetime.fromisoformat(ts) for ts in timestamps}
    print(existing_timestamps)
    # Filter prepared_data
    filtered_data = []
    for entry in prepared_data:
        # Get the date value from the entry
        date_value = entry.get(date_key)

        # Handle datetime objects and date strings
        if isinstance(date_value, datetime):
            # If it's already a datetime object, use it directly
            entry_datetime = date_value
        elif isinstance(date_value, str):
            try:
                # Try parsing the date string into a datetime object
                entry_datetime = datetime.fromisoformat(date_value)
            except ValueError:
                # Skip if the date string is not in a valid format
                continue
        else:
            # Skip if the date value is not a datetime object or string
            continue
        print(entry_datetime)
        # Check if the entry's datetime exists in the timestamps list
        if entry_datetime not in existing_timestamps:
            filtered_data.append(entry)

    return filtered_data