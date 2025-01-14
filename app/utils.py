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
from fhir.resources.patient import Patient as fhirPatient
from fhir.resources.humanname import HumanName
from datetime import date, datetime
from rdflib import Graph, URIRef, Literal, XSD, OWL
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace


CLIENT_ID = '238ZN5'
CLIENT_SECRET = '2c1f3aa0a96bc067d34714c281b953d0'
redirect_uri = 'https://pghdtofhir.onrender.com/wearable/fitbit_auth_callback'

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

def copy_instance(new_g, instance, mapping_dict):
    g = Graph()
    g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")
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
    smtp_server = "emr.abdullahikawu.org"
    smtp_port = 465  # SSL port
    sender_email = "info@emr.abdullahikawu.org"
    password = "[,p@cO$ai4B5"
    #receiver_email = "receiver@example.com"  # Replace with the actual recipient's email

    # Create the email
    message = MIMEMultipart()
    message["From"] = "Healthcare Provider <info@emr.abdullahikawu.org>"
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
        print("✅ Email sent successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

def add_metadata_to_graph(new_g, identity, other_data=None):
    # define namespace 
    pghdprovo = Namespace("https://w3id.org/pghdprovo/")
    wearpghdprovo = Namespace("https://w3id.org/wearpghdprovo/")
    prov = Namespace("http://www.w3.org/ns/prov#")
    foaf = Namespace("http://xmlns.com/foaf/0.1/gender")
    wearable_name = ""
    if other_data:
        wearable_name = other_data.get("wearable_name", "")
    # add a instance
    # g.add((subject, predicate, object))

    g = Graph()
    g.parse("static/rdf_files/wearpghdprovo-onto-template.ttl", format="turtle")

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

    meta_data = {
        "pghdprovo:Patient":{
            "givenName": identity.patient.name,
            "birthday":"",
            "address":"",
            "gender":"",
            "userid":identity.patient.user_id,
            "phoneNumber":identity.patient.phone_number,
        },
        "pghdprovo:Practitioner":{
            "givenName":identity.practitioner.name,
            "birthday":"",
            "address":"",
            "gender":"",
            "userid": identity.practitioner.user_id,
            "phoneNumber": identity.practitioner.phone_number,
            "role":""
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
        "pghdprovo:PGHD":{
            "name":"",
            "value":"",
            'unit': "",
            'hasTimestamp': "",
            "dataSource":""
        },
        "pghdprovo:Application":{
            "appName": identity.ehr_system.name
        },
        "pghdprovo:PatientRelative":{
            "givenName":"",
            "birthday":"",
            "address":"",
            "gender":"",
            "userid":"",
            "phoneNumber":"",
            "relationship":""
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
            # print (row.subject, row.property, row.object, sep=") , (")
            new_subject = copy_instance(new_g, row.subject, mapping_dict)
            # print(str(row.subject), str(new_subject), sep=" : ")

            # if object is an individual
            if isinstance(row.object, URIRef):
                if OWL.Class not in list(g.objects(row.object, RDF.type)):
                    new_object = copy_instance(new_g, row.object, mapping_dict)
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
            print("\n\n")

    # Find new copy of instances from earlier defined
    new_instances = {}
    for i in [mapping_dict[mapped] for mapped in mapping_dict.keys()]:
        instance_class = get_main_class(g, URIRef(i))
        if instance_class:
            class_name = get_entity_name(instance_class)
            new_instances[class_name] = URIRef(i)
    # print(new_instances)
    return new_instances
