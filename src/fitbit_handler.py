################ Fitbit_to_Cedar.py #############################
# PGHD Project
# Description: This script fetches the data from fitbit and pushes it to CEDAR
##################################################################

#importing libraries
from threading import current_thread
import gather_keys_oauth2 as Oauth2
import fitbit
import pandas as pd 
import datetime 
import json
import requests

#fitbit credentials
Start_time =  datetime.now()
CLIENT_ID = '23RGC3'
CLIENT_SECRET = '14de2f34d59a224fe4f0a4635de46360'
# cedar_url = 'https://resource.metadatacenter.org/template-instances'
# cedar_api_key = 'apiKey f1b9368fb41c87452d4a6d65524bde5137870db4ec456d6882546ef8d427c183'


##fitbit authentication
def fitbit_authentication():
    server=Oauth2.OAuth2Server(CLIENT_ID, CLIENT_SECRET)
    server.browser_authorize()
    ACCESS_TOKEN=str(server.fitbit.client.session.token['access_token'])
    REFRESH_TOKEN=str(server.fitbit.client.session.token['refresh_token'])
    auth2_client=fitbit.Fitbit(CLIENT_ID,CLIENT_SECRET,oauth2=True,access_token=ACCESS_TOKEN,refresh_token=REFRESH_TOKEN)
    return auth2_client


auth2_client = fitbit_authentication()

#Fetch data from Fitbit 
body = auth2_client.body(date=Start_time)
activities = auth2_client.activities(date=Start_time)
sleep = auth2_client.sleep(date=Start_time)
fat = body['body']['fat'] if 'fat' in body['body'] else 0
bmi = body['body']['bmi'] if 'bmi' in body['body'] else 0
fairlyActiveMinutes = activities['summary']['fairlyActiveMinutes'] if 'fairlyActiveMinutes' in activities['summary'] else 0
lightlyActiveMinutes = activities['summary']['lightlyActiveMinutes'] if 'lightlyActiveMinutes' in activities['summary'] else 0
sedentaryMinutes = activities['summary']['sedentaryMinutes'] if 'sedentaryMinutes' in activities['summary'] else 0
veryActiveMinutes = activities['summary']['veryActiveMinutes'] if 'veryActiveMinutes' in activities['summary'] else 0
if len(sleep['sleep']) > 0:
    sleep_duration = sleep['sleep'][0]['duration'] if 'duration' in sleep['sleep'][0] else 0
else:
    sleep_duration = 0
if len(sleep['sleep']) > 0:
    sleep_efficiency = sleep['sleep'][0]['duration'] if 'efficiency' in sleep['sleep'][0] else 0
else:
    sleep_efficiency = 0
restingHeartRate = activities['summary']['restingHeartRate'] if 'restingHeartRate' in activities['summary'] else 0
Total_distances = activities['summary']['distances'][0]['distance'] if 'distances' in activities['summary'] else 0
calories_burnt = activities['summary']['caloriesOut'] if 'caloriesOut' in activities['summary'] else 0
steps_count = activities['summary']['steps'] if 'steps' in activities['summary'] else 0


def puish_data_to_cedar():
    cedar_url = 'https://resource.metadatacenter.org/template-instances'
    cedar_api_key = 'apiKey 62838dcb5b6359a1a93baeeef907669813ec431437b168efde17a61c254b3355'
    
#push data to CEDAR 
    cedar_template = open('templates/pghd_connect_template.json')
    data = json.load(cedar_template)
    data['userid']['@value'] = CLIENT_ID

    data['Fat']['@value'] = str(fat)
    data['BMI']['@value'] = str(bmi)
    data['date time']['@value'] =Start_time.strftime('%Y-%m-%dT%H:%M:%S')
    data['Fairly active minutes']['@value'] = str(fairlyActiveMinutes)
    data['lightly active minutes']['@value'] = str(lightlyActiveMinutes)
    data['sedentary minutes']['@value'] = str(sedentaryMinutes)
    data['very active minutes']['@value'] = str(veryActiveMinutes)
    data['duration']['@value'] = str(sleep_duration)
    data['efficiency']['@value'] = str(sleep_efficiency)
    data['resting heart rate']['@value'] = str(restingHeartRate)
    data['steps']['@value'] = str(steps_count)

    # data['schema:name'] = f'VHD {Start_time}' ##VHD 2023-11-14 00:00:00

    cedar_template.close()

#push data to cedar 
    try:
        response = requests.post(cedar_url, json=data, headers={'Content-Type': 'application/json',
                                                     'Accept': 'application/json',
                                                     'Authorization': cedar_api_key})
        if response.status_code == 201:  # Assuming a successful creation response
            # print(Start_time, "Data successfully pushed to Cedar!")
            msg = "Data successfully pushed to Cedar!"
        else:
            print(f"Error: {response.status_code}, {response.text},{Start_time}")
            msg =  f"Error: {response.status_code}, {response.text},  "

    except Exception as e:
        # print(f"An error occurred: {e},{Start_time}")
        msg = f"An error occurred: {e},  "
    
    return response, msg

response,msg   = puish_data_to_cedar()
print(msg)
print(response.status_code)

#TODO 
# 1. Check the response from cedar and dicet it to get the uri 
# 2. Save the uri 
# 3. Push the uri to the cedar template instance

