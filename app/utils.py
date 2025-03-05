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

def send_authorisation_email(receiver_email, auth_link, name=""):
    sender_email = SENDER_EMAIL
    smtp_server = SMTP_SERVER
    password = SMTP_PASSWORD
    smtp_port = SMTP_PORT

    # Create the email
    message = MIMEMultipart()
    message["From"] = f"Healthcare Provider <{sender_email}>"
    message["To"] = receiver_email
    message["Subject"] = "Authorize Fitbit Data Access"

    # Minimal HTML Email Body
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 10px; background-color: #f9fafc;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 5px;">
        <h2 style="color: #2c3e50; text-align: center;">Healthcare Data Authorization</h2>
        <p><strong>Dear Patient,</strong></p>
        <p>Please click the button below to authorize access to your Fitbit data for your healthcare provider {name}.</p>
        <p style="text-align: center; margin: 20px 0;">
            <a href="{auth_link}" 
            style="background-color: #0078d7; color: #ffffff; text-decoration: none; padding: 10px 20px; border-radius: 5px; display: inline-block;">
            Authorize Access
            </a>
        </p>
        <p style="font-size: 12px; color: #555555; margin-top: 20px;">
            <em>Note:</em> By authorizing access to your Fitbit data, you consent to its use for clinical decision-making and research. 
            You can revoke this access anytime from your Fitbit account.
        </p>
        <p style="text-align: center; font-size: 10px; color: #888888; margin-top: 20px; border-top: 1px solid #eeeeee; padding-top: 10px;">
            This is an automated message. Please do not reply.
        </p>
        </div>
    </body>
    </html>
    """
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
                "deviceModel":""
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

def verify_resources(data):
    """
    Verifies the existence of Patient, Practitioner, Encounter, and Organization resources.
    """

    patient_user_id = data["meta-data"]["patient"].get("user_id", None)
    #if data["authentication"].get("patient", None)
    if not patient_user_id:
        abort(400, "Error, patient user_id not provided.")
    if not check_resource_existence("Patient", patient_user_id):
        abort(404, f"Patient with ID '{patient_user_id}' does not exist on FHIR server.")

    practitioner_user_id = data["meta-data"]["practitioner"].get("user_id", None)
    # if data["authentication"].get("practitioner", None) 
    if not practitioner_user_id:
        abort(400, "Error, practitioner user_id not provided.")
    if not check_resource_existence("Practitioner", practitioner_user_id):
        abort(404, f"Practitioner with ID '{practitioner_user_id}' does not exist on FHIR server.")


    if data["authentication"].get("organization", None):
        organization_user_id = data["meta-data"]["organization"].get("org_id", None)
        if not organization_user_id:
            abort(400, "Error, organization user_id not provided.")
        if not check_resource_existence("Organization", organization_user_id):
            abort(404, f"Organization with ID '{organization_user_id}' does not exist on FHIR server.")
    
    # check encounter
    encounter_id = data["meta-data"].get("encounter_id")
    if encounter_id and not check_resource_existence("Encounter", encounter_id):
        abort(404, f"Encounter with ID '{encounter_id}' does not exist on FHIR server.")

    # Check patient email
    if data["request_type"] == "fitbit":
        patient_email = data["meta-data"]["patient"].get("email", None)
        # if data["authorisation"]["patient"].get("type", None) == "email":
        if not patient_email:
            abort(400, "Error, patient email not provided.")

    # find patient number
    if data["request_type"] == "IVR":
        patient_phone_number = data["meta-data"]["patient"].get("phone_number", None)
        if not patient_phone_number:
            abort(400, "Error, patient number not provided.")
    
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
    request_type = "Wearable" if request_type != "IVR" else request_type
    request_data_type = request_data.get("request_data_type", None)
    patient_id = request_data["meta-data"]["patient"]["user_id"]
    practitioner_id = request_data["meta-data"]["practitioner"]["user_id"]
    organization_id = request_data["meta-data"]["organization"].get("org_id", None)
    encounter_id = request_data.get("encounter", None)
    organization = None
    encounter = None
    device = None
    
    # creeate organization resource
    if not request_data["authentication"].get("organization", None):
        organization_id = "urn:uuid:organization-1"
        org = request_data["meta-data"]["organization"]
        org_name = org.get("name", None)
        try:
            organization = FhirOrganization(
                id="organization-1",
                name=org_name,
                identifier=[
                    {
                        "system": "urn:uuid",
                        "value": str(uuid.uuid4())
                    }
                ],
            )
        except ValueError as e:
            print("Organizartion error: ", e.errors())
    else:
        organization_id = f"Organization?identifier={organization_id}"
    
    # create encounter resource
    if not request_data.get("encounter", None):
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
    else:
        encounter_id = f"Encounter?identifier={encounter_id}"
    
    # create device resource
    if request_type == "Wearable":
        try:
            device = Device(
                id="device-1",
                identifier=[
                    {
                        "system": "urn:uuid",
                        "value": str(uuid.uuid4())
                    }
                ],
                type={
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "49062001",
                            "display": "Device"
                        }
                    ]
                },
                manufacturer="Fitbit Inc.",
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
        "vital-signs": ["Diastolic blood pressure", "Systolic blood pressure", "Heart rate", "restingHeartRate"],
        "activity": ["steps", "sleepDuration", "calories"]
    }
    
    triple_store = Graph(store=store)
    # triple_store_loc = "static/rdf_files/wearpghdprovo-onto-store.ttl"
    # triple_store.parse(triple_store_loc, format="turtle")

    query = f"""
    SELECT ?subject ?name ?value ?source ?timestamp ?description ?label
    WHERE {{
        ?subject a pghdprovo:PGHD .
        ?subject pghdprovo:name ?name .
        ?subject pghdprovo:value ?value .
        ?subject pghdprovo:dataSource ?source .
        ?subject pghdprovo:hasTimestamp ?timestamp .
        FILTER (?timestamp >= "{start_date}"^^xsd:dateTime && ?timestamp <= "{end_date}"^^xsd:dateTime) .
        FILTER (?source = "{request_type}") .
        OPTIONAL {{
            FILTER (?name = "{request_data_type}") .
            ?subject rdfs:comment ?description .
            ?subject rdfs:label ?label .
        }}
    }}
    """
    result = triple_store.query(query_header + query)
    
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
                subject={"reference": f"Patient?identifier={patient_id}"},
                encounter={"reference": encounter_id},
                device={"reference": "urn:uuid:device-1"} if device else None,
                valueQuantity=value_set,
                effectiveDateTime=(record.timestamp.value).strftime("%Y-%m-%dT%H:%M:%SZ")
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
                    "reference": {"reference": "urn:uuid:device-1"}  if device else None
                }
            }]
        )
    except ValueError as e:
        print(e.errors())
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
        bundle.entry.append(BundleEntry(
            resource=device,
            request={
                "method": "POST",
                "url": "Device"
            },
            fullUrl=f"urn:uuid:device-1"
        ))

    # Add Organization resource (if defined)
    if organization:
        bundle.entry.append(BundleEntry(
            resource=organization,
            request={
                "method": "POST",
                "url": "Organization"
            },
            fullUrl=organization_id
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
