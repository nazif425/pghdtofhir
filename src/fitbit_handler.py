################ fitbit_handler.py #############################
# PGHD Project
# Description: This script fetches the data from fitbit and pushes it to CEDAR
##################################################################

#importing libraries
from threading import current_thread
import gather_keys_oauth2 as Oauth2
import fitbit
import pandas as pd 
from datetime import datetime
import json
import requests

from urllib import parse
from rdflib import Graph, Namespace
from rdflib.namespace import XSD
from rdflib.plugins.sparql import prepareQuery


def fitbit_authentication(user):
    server=Oauth2.OAuth2Server(user["CLIENT_ID"], user["CLIENT_SECRET"])
    server.browser_authorize()
    ACCESS_TOKEN=str(server.fitbit.client.session.token['access_token'])
    REFRESH_TOKEN=str(server.fitbit.client.session.token['refresh_token'])
    auth2_client=fitbit.Fitbit(user["CLIENT_ID"], user["CLIENT_SECRET"], oauth2=True, access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN)
    return auth2_client


def get_fitbit_data(start_time, auth2_client):
    body = auth2_client.body(date=start_time)
    activities = auth2_client.activities(date=start_time)
    sleep = auth2_client.sleep(date=start_time)
    fat = body['body']['fat'] if 'fat' in body['body'] else None
    bmi = body['body']['bmi'] if 'bmi' in body['body'] else None 
    fairlyActiveMinutes = activities['summary']['fairlyActiveMinutes'] if 'fairlyActiveMinutes' in activities['summary'] else None
    lightlyActiveMinutes = activities['summary']['lightlyActiveMinutes'] if 'lightlyActiveMinutes' in activities['summary'] else None
    sedentaryMinutes = activities['summary']['sedentaryMinutes'] if 'sedentaryMinutes' in activities['summary'] else None
    veryActiveMinutes = activities['summary']['veryActiveMinutes'] if 'veryActiveMinutes' in activities['summary'] else None
    if len(sleep['sleep']) > 0:
        sleep_duration = sleep['sleep'][0]['duration'] if 'duration' in sleep['sleep'][0] else None
    else:
        sleep_duration = None
    if len(sleep['sleep']) > 0:
        sleep_efficiency = sleep['sleep'][0]['duration'] if 'efficiency' in sleep['sleep'][0] else None
    else:
        sleep_efficiency = None
    restingHeartRate = activities['summary']['restingHeartRate'] if 'restingHeartRate' in activities['summary'] else None
    total_distances = activities['summary']['distances'][0]['distance'] if 'distances' in activities['summary'] else None
    calories_burnt = activities['summary']['caloriesOut'] if 'caloriesOut' in activities['summary'] else None
    steps_count = activities['summary']['steps'] if 'steps' in activities['summary'] else None
    
    fitbit_data = {
        "fat": fat,
        "bmi": bmi,
        "fairlyActiveMinutes": fairlyActiveMinutes,
        "lightlyActiveMinutes": lightlyActiveMinutes,
        "sedentaryMinutes": sedentaryMinutes,
        "veryActiveMinutes": veryActiveMinutes,
        "sleep_duration": sleep_duration,
        "sleep_efficiency": sleep_efficiency,
        "restingHeartRate": restingHeartRate,
        "total_distances": total_distances,
        "calories_burnt": calories_burnt,
        "steps_count": steps_count
    }

    return fitbit_data
 


def push_data_to_cedar(data, start_time, user):
    cedar_url = 'https://resource.metadatacenter.org/template-instances'
    with open('../.secrets.json') as secrets:
        cedar_api_key = json.load(secrets)["authkey_RENS"]
    
    cedar_template = open('templates/fitbit_template.json')
    data = json.load(cedar_template)
    current_time = datetime.now()

    data['Fat']['@value'] = str(data.get("fat"))
    data['BMI']['@value'] = str(data.get("bmi"))
    data['Date']['@value'] =start_time.strftime('%Y-%m-%dT%H:%M:%S') # COMMENT BY RK: Can we get the observation time from the fitbit? According to the description it should also only be date.
    data['Fairly active minutes']['@value'] = str(data.get("fairlyActiveMinutes"))
    data['Lightly active minutes']['@value'] = str(data.get("lightlyActiveMinutes"))
    data['Sedentary minutes']['@value'] = str(data.get("sedentaryMinutes"))
    data['Very active minutes']['@value'] = str(data.get("veryActiveMinutes"))
    data['Sleep duration']['@value'] = str(data.get("sleep_duration"))
    data['Sleep efficiency']['@value'] = str(data.get("sleep_efficiency"))
    data['Resting heart rate']['@value'] = str(data.get("restingHeartRate"))
    data['Total distance']['@value'] = str(data.get("total_distances"))
    data['Calories burnt']['@value'] = str(data.get("calories_burnt"))
    data['Steps']['@value'] = str(data.get("steps_count"))
    data['schema:name'] = f"PGHD_FB {current_time.strftime('%Y-%m-%d')}"
    
    cedar_template.close()
    


    # COMMENT BY RK: In production we should push to predefined folders so that things aren't lying around everywhere. 
    # you can do this by adding params = {'folder_id': folder_id} to the POST request below.
    try:
        response = requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                                'Accept': 'application/json',
                                                                'Authorization': cedar_api_key})
        if response.status_code == 201:  # Assuming a successful creation response
            
            msg = "Data successfully pushed to Cedar!"
            cedar_data_URI = response.json()["@id"]
        else:
            print(f"Error: {response.status_code}, {response.text},{start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
         
        msg = f"An error occurred: {e},  "


    # Setup PGHD_CONNECT
    cedar_template_connect = open('templates/pghd_connect_template.json')
    connect_ontology_prefix = 'https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/'
    connect_data = json.load(cedar_template_connect)
     
    connect_data['Patient']['@id'] = str(user['cedar_registration_URI'])
    connect_data['collected_PGHD']['@id'] = cedar_data_URI
    connect_data['source_of_PGHD']['@id'] = str(connect_ontology_prefix + 'fitbit')
    connect_data['source_of_PGHD']['rdfs:label'] = str('fitbit')
    connect_data['schema:name'] = f"PGHD_FB CNT {current_time.strftime('%Y-%m-%d')}"

    try:
        response = requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                 'Accept': 'application/json',
                                                 'Authorization': cedar_api_key})
        if response.status_code == 201:  # Assuming a successful creation response
            msg = "Data successfully pushed to Cedar!"
        else:
            print(f"Error: {response.status_code}, {response.text},{start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
        msg = f"An error occurred: {e},  "
        

    return msg


def get_fitbit_users(local_registrations=False):
    registrations_file = None #'triple_store/registrations.ttl'

    # This clause can be used if the list of registered patients is stored localy at clinic side and can be easily retrieved (or queried through e.g. AG)
    # For the purpose of the pilot we store all data on CEDAR and import from there 
    g = Graph()
    if local_registrations:
        g.parse(registrations_file)
    else:
        with open('.secrets.json') as secrets:
            cedar_api_key = json.load(secrets)["authkey_RENS"]

        get_instances_url =  "https://resource.metadatacenter.org/folders/"
        get_instancedata_url = "https://resource.metadatacenter.org/template-instances/"
        headers = {"accept": "application/json", "authorization": cedar_api_key}

        # Get all patients - this works for now but is not very scalable. I think it is better though than keeping all patients in memory continuously (RK)
        # Step 1: Find the URIs of all registered patient instances
        registration_folder_id = "https://repo.metadatacenter.org/folders/6547e00c-3e91-4c50-b0c9-3185ea68a39f" 
        url = get_instances_url + parse.quote_plus(registration_folder_id) + '/contents'

        response = requests.get(url, headers=headers)
        response = response.json()
        #print(response)
        
        # Make an RDFlib Graph on which we can query for the dashboard
        g = Graph()

        # Request each instance individually and add it to the graph
        cedar_instances = response["resources"]
        #print(cedar_instances)
        N = len(cedar_instances)
        #print(f"Found {N} instances to import.")
        for instance in cedar_instances:
            
            instance_ID = parse.quote_plus(instance["@id"]) # make the instance ID url-safe
            print(instance_ID)
            # Send out get request for instance data
            url = get_instancedata_url + instance_ID
            response = requests.get(url, headers=headers)

            # Add data to the graph
            g.parse(data=response.json(), format='json-ld')


    query_string = f"""
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>     
        SELECT ?id ?code ?patient_id
        WHERE{{
            ?id <http://schema.org/isBasedOn>  <https://repo.metadatacenter.org/templates/f49d788e-f611-4525-90e9-dd21204b51fa> ;
                pghdc:fitbitID ?client_id ;
                pghdc:fitbitSecret ?client_secret .
        }}
        """
    
    # Execute query on graph using RDFLib. Check performance in case of large store
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    query = prepareQuery(query_string, initNs={'pghdc': pghdc, 'xsd': XSD})
    res = g.query(query)

    users = []
    for row in res:
        users.append({
            "CLIENT_ID": row.client_id,
            "CLIENT_SECRET": row.client_secret,
            "CEDAR_registration_ID": row.id
        })


def handle_fitbit_data(user):
    start_time = datetime(2023, 11, 11) # What should this be? Probably dynamic instead of hard coded at least right
    auth2_client = fitbit_authentication(user)
    fitbit_data = get_fitbit_data(start_time, auth2_client)
    push_data_to_cedar(fitbit_data, start_time, user)
    

def main():
    fitbit_users = get_fitbit_users()
    for user in fitbit_users:
        handle_fitbit_data(user)


if __name__ == "__main__":
    main()
    



#TODO 
# 1. fix the gather_keys_oauth2 importation error 

