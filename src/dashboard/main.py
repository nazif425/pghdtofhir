import matplotlib.pyplot as plt

import json
import requests
from urllib import parse

from rdflib import Graph
import streamlit as st

from plotting import plot_bp, plot_fitbit


def set_styles():
    # Set matplotlib styles
    plt.style.use('bmh')

@st.cache_data
def retrieve_data_cedar():
    try:
        g = Graph()
        g.parse('mock_data.ttl')
        return g
    except FileNotFoundError:
        print("No existing file discovered. Starting data import from CEDAR..")
    
    with open('../.secrets.json') as secrets:
        cedar_api_key = json.load(secrets)["authkey_RENS"]

    # Right now, we get the URIs of all instances in the mock_data folder and then separately query and parse each file
    # Is there a more efficient method to do this? e.g. query all contents within a folder at the same time with /folders/{folder_id}/contents_extract ???
    url = "https://resource.metadatacenter.org/folders/https%3A%2F%2Frepo.metadatacenter.org%2Ffolders%2F422ba135-4215-433a-b2d2-1d9a3fee7317/contents" 
    headers = {"accept": "application/json", "authorization": cedar_api_key}
    response = requests.get(url, headers=headers)
    response = response.json()

    # Make an RDFlib Graph on which we can query for the dashboard
    g = Graph()
    patients = [] # Keep track of which patients have been added to the graph

    # Request each instance individually and add it to the graph
    cedar_instances = response["resources"]
    N = len(cedar_instances)
    print(f"Found {N} instances to import. (Corresponding to {N//2} data entries.)")
    for i, instance in enumerate(cedar_instances):
        instance_ID = parse.quote_plus(instance["@id"]) # make the instance ID url-safe

        # Send out get request for instance data
        url = "https://resource.metadatacenter.org/template-instances/" + instance_ID
        #print(url)
        
        response = requests.get(url, headers=headers)

        # Import data
        instance_data = response.json()
        g.parse(data=instance_data, format='json-ld')

        # Try import patient information, if it hasn't been done yet
        try:
            # This is not the fastest method, but data is cached anywho. Speed up?
            print("Checking Patient ID")
            patient_reg_ID = instance_data["Patient"]["@id"]
            if patient_reg_ID in patients:
                print("patient ID already included")
                patient_reg_ID = None
        except KeyError:
            patient_reg_ID = None

        if patient_reg_ID is not None: # Do this for error catching
            print("patient ID not yet included")
            patients.append(patient_reg_ID)
            patient_reg_ID = parse.quote_plus(patient_reg_ID)
            patient_url = "https://resource.metadatacenter.org/template-instances/" + patient_reg_ID
            patient_response = requests.get(patient_url, headers=headers)
            patient_data = patient_response.json()
            print(patient_data)
            g.parse(data=patient_data, format='json-ld')

        


        print(f'Finished import instance {i+1}/{N}')#, end='\r')

    g.serialize(format='ttl', destination='mock_data.ttl')
    print('Completed.\n\n')

    return g


def setup_dashboard():
    st.write("Welcome to the PGHD dashboard.")
    st.sidebar.write("Tick the boxes of the attributes you want to see plotted below.")
    st.sidebar.write("")
    
    plot_attrs = {}
    st.sidebar.write("Blood Pressure Values")
    plot_attrs["pulse"]  =  st.sidebar.checkbox("Pulse Rate")
    plot_attrs["sys_bp"] =  st.sidebar.checkbox("Systolic Blood Pressure")
    plot_attrs["dia_bp"] =  st.sidebar.checkbox("Diastolic Blood Pressure")

    st.sidebar.write("")
    st.sidebar.write("Fitbit Values")
    # TODO: HAROLD ADD FITBIT PLOT VALUES HERE (SEE ABOVE)
    plot_attrs["fitbit"]= st.sidebar.checkbox("All Fitbit Values")

    return plot_attrs

def main(): 
    set_styles()
    g = retrieve_data_cedar()

    plot_attrs = setup_dashboard()
    if plot_attrs["pulse"] or plot_attrs["sys_bp"] or plot_attrs["dia_bp"]:
        plot_bp(g, plot_attrs) 

    if plot_attrs["fitbit"]:
        plot_fitbit(g, plot_attrs)


if __name__ == '__main__':
    main()

