
import streamlit as st
#import mpld3
#from mpld3 import plugins
import streamlit.components.v1 as components
from datetime import date, timedelta

import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import pandas as pd
from datetime import date

from rdflib import Namespace
from rdflib.namespace import XSD, RDFS
from rdflib.plugins.sparql import prepareQuery


def process_simple_query(graph, query_string):
    ti = Namespace("https://github.com/RenVit318/financial_dashboard/blob/main/code/vocab/transaction_info.ttl#")
    query = prepareQuery(query_string, initNs={"ti": ti, "xsd": XSD})
    res = graph.query(query)

    return res


def plot_trend(df, ydata, label, c, size=8, highlight_outliers=False):
    #mean = np.mean(y)
    #std = np.std(y)
    #if highlight_outliers:
    #    outliers = np.abs((y - mean)/std) > 1
    #    st.plotly_chart(x[outliers], y[outliers], lw=0, marker='X', color=c, markersize=2*size)
    #else:
    #    outliers = np.full(len(x), False)
    #st.plotly_chart(x[~outliers], y[~outliers], lw=0, marker='o', color=c, markersize=size, label=label)
    #plt.axhline(mean, color=c, ls='--', alpha=0.7)
    fig = px.line(df, x='date', y=['sys_bp', 'dia_bp'])
    return fig
    

def plot_bp(g, atts_to_plot):
    query_str = f"""
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX bp_aux: <https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/>
        PREFIX smash: <http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pulse ?sys_bp ?dia_bp ?date ?loc ?person ?pos
        WHERE {{
            ?y pghdc:patient ?x ;
               pghdc:collected_PGHD ?z . 
            ?x pghdc:patientID '{atts_to_plot['patient']}'^^xsd:int .
            ?z smash:hasSystolicBloodPressureValue ?sys_bp ;
               smash:hasDiastolicBloodPressureValue ?dia_bp ;
               smash:hasPulseRate ?pulse ;
               bp_aux:CollectionLocation ?loc_uri ;
               bp_aux:CollectionPerson ?person_uri ;
               bp_aux:CollectionPosition ?pos_uri ;
               dc:date ?date .

            ?loc_uri    rdfs:label ?loc .
            ?person_uri rdfs:label ?person .
            ?pos_uri    rdfs:label ?pos .
        }}
    """

    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    smash = Namespace("http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#")
    dc    = Namespace("http://purl.org/dc/elements/1.1/")
    bp_aux= Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/")
    query = prepareQuery(query_str, initNs={"pghdc": pghdc, "bp_aux": bp_aux, "smash": smash, "dc": dc, "xsd": XSD, "rdfs": RDFS})
    res = g.query(query)

    N = len(res)
    data = pd.DataFrame({
        'date'  : np.zeros(N, dtype=object),
        'pulse' : np.zeros(N, dtype=float),
        'sys_bp': np.zeros(N, dtype=float),
        'dia_bp': np.zeros(N, dtype=float),
        'loc'   : np.zeros(N, dtype=str),
        'person': np.zeros(N, dtype=str),
        'pos'   : np.zeros(N, dtype=str),
    })

    for i, row in enumerate(res):
        data.loc[i, 'date']   = date.fromisoformat(row.date)
        data.loc[i, 'pulse']  = float(row.pulse)
        data.loc[i, 'sys_bp'] = float(row.sys_bp)
        data.loc[i, 'dia_bp'] = float(row.dia_bp)
        data.loc[i, 'loc']    = row.loc
        data.loc[i, 'person'] = row.person
        data.loc[i, 'pos']    = row.pos

    data = data.sort_values(by='date')

    #unique_dates, idxs = np.unique(data['date'], return_index=True)
    #min_date = np.min(unique_dates)
    #max_date = np.max(unique_dates)
    #delta = timedelta(days=1)
    #start_state = (np.max((min_date, max_date - 2 * delta)), max_date)

    #daterange = st.slider(label='Select date range', min_value=min_date, max_value=max_date,
    #                      value=start_state)

    # Plotting
    ydata = []
    if atts_to_plot['pulse']:
        ydata.append('pulse')
    if atts_to_plot['sys_bp']:
        ydata.append('sys_bp')
    if atts_to_plot['dia_bp']:
        ydata.append('dia_bp')

    if len(ydata) > 0:
        fig = px.line(data, x='date', y=ydata, custom_data=['loc', 'person', 'pos'], 
                      title=f"IVR Blood Pressure Monitor Data", 
                      markers=True)

        fig.update_traces(
            hovertemplate="<br>".join([
                "Date: %{x}",
                "Val:  %{y}",
                "Location: %{customdata[0]}",
                "Person:   %{customdata[1]}",
                "Position: %{customdata[2]}",
            ])
        )
        st.plotly_chart(fig)



    # Show the data in a table
    show_data = st.checkbox("Click here to view the data")
    if show_data: 
        #df = pd.DataFrame(data)
        st.dataframe(data, 
                     use_container_width=True, hide_index=True,
                     column_config={
                        "date": "Date",
                        "pulse": "Pulse Rate",
                        "sys_bp": "Systolic BP",
                        "dia_bp": "Diastolic BP",
                        "loc": "Location",
                        "person": "Person",
                        "pos": "Position"
                     })



def plot_fitbit(g, plot_attrs):
    st.write('Plot fitbit stuff here..')
    fig = plt.figure()

    st.pyplot(fig)

## help me uppdate this for the fitbit stuff
    query_str = """
        PREFIX pghdc: <https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/>
        PREFIX bp_aux: <https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/>
        PREFIX smash: <http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?date ?fairlyActiveMinutes ?lightlyActiveMinutes ?sedentaryMinutes ?veryActiveMinutes ?sleep_duration ?sleep_efficiency ?restingHeartRate ?steps_count 
        WHERE {
            ?y pghdc:patient ?x ;
               pghdc:collected_PGHD ?z . 
            ?x pghdc:patientID "1234"^^xsd:int .
            ?z smash:hasSystolicBloodPressureValue ?sys_bp ;
               smash:hasDiastolicBloodPressureValue ?dia_bp ;
               smash:hasPulseRate ?pulse ;
               bp_aux:CollectionLocation ?loc_uri ;
               bp_aux:CollectionPerson ?person_uri ;
               bp_aux:CollectionPosition ?pos_uri ;
               dc:date ?date .

            ?loc_uri    rdfs:label ?loc .
            ?person_uri rdfs:label ?person .
            ?pos_uri    rdfs:label ?pos .
        }
    """
    pghdc = Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/pghd_connect/")
    smash = Namespace("http://aimlab.cs.uoregon.edu/smash/ontologies/biomarker.owl#")
    dc    = Namespace("http://purl.org/dc/elements/1.1/")
    bp_aux= Namespace("https://github.com/RenVit318/pghd/tree/main/src/vocab/auxillary_info/")
    query = prepareQuery(query_str, initNs={"pghdc": pghdc, "bp_aux": bp_aux, "smash": smash, "dc": dc, "xsd": XSD, "rdfs": RDFS})
    res = g.query(query)
    

    N = len(res)
    data = pd.DataFrame({
        'date'   : np.zeros(N, dtype=str),
        'fairlyActiveMinutes'  : np.zeros(N, dtype=object),
        'lightlyActiveMinutes' : np.zeros(N, dtype=float),
        'sedentaryMinutes': np.zeros(N, dtype=float),
        'veryActiveMinutes': np.zeros(N, dtype=float),
        'sleep_duration'   : np.zeros(N, dtype=str),
        'sleep_efficiency': np.zeros(N, dtype=str),
        'restingHeartRate'   : np.zeros(N, dtype=str),
        'steps_count'   : np.zeros(N, dtype=str),
    })
    
    for i, row in enumerate(res):
        data.loc[i, 'date']   = date.fromisoformat(row.date)
        data.loc[i, 'fairlyActiveMinutes']  = float(row.pulse)
        data.loc[i, 'lightlyActiveMinutes'] = float(row.sys_bp)
        data.loc[i, 'sedentaryMinutes'] = float(row.dia_bp)
        data.loc[i, 'veryActiveMinutes']    = row.loc
        data.loc[i, 'sleep_duration'] = row.person
        data.loc[i, 'sleep_efficiency']    = row.pos
        data.loc[i, 'restingHeartRate']    = row.pos
        data.loc[i, 'steps_count']    = row.pos


    unique_dates, idxs = np.unique(data['date'], return_index=True)
    min_date = np.min(unique_dates)
    max_date = np.max(unique_dates)
    delta = timedelta(days=1)
    start_state = (np.max((min_date, max_date - 2 * delta)), max_date)

    daterange = st.slider(label='Select date range', min_value=min_date, max_value=max_date,
                          value=start_state)
    
    
        # Plotting
    fig = plt.figure()
    if plot_attrs['pulse']:
        plot_trend(data.loc[idxs, 'date'], data.loc[idxs, 'pulse'], c='C0', label="Pulse Rate")
    if plot_attrs['sys_bp']:
        plot_trend(data.loc[idxs, 'date'], data.loc[idxs, 'sys_bp'], c='C1', label="Systolic Blood Pressure")
    if plot_attrs['dia_bp']:
        plot_trend(data.loc[idxs, 'date'], data.loc[idxs, 'dia_bp'], c='C2', label="Diastolic Blood Pressure")
  
    plt.axhline(y=0, lw=1, c='black')
    plt.xlim(daterange)

    plt.xlabel('Date of measurement')
    plt.ylabel('Fitbit Data Value')
    plt.title('PGHD - FITBIT Data')

    # Setup proper xticks
    ticks = []
    labels = []
    done = False
    curr_date = daterange[0]
    while not done:
        if curr_date == daterange[1]:
            done = True
        ticks.append(curr_date)
        labels.append(curr_date.strftime("%d-%m"))
        curr_date += delta 
    plt.xticks(ticks=ticks, labels=labels, rotation=60)

    plt.legend()
    
    st.pyplot(fig)


    show_data = st.checkbox("Click here to view the data")
    if show_data: 
        df = pd.DataFrame(data)
        st.dataframe(data, 
                     use_container_width=True, hide_index=True,
                     column_config={
                        "date": "Date",
                        "fairlyActiveMinutes": "Fairly Active Minutes",
                        "lightlyActiveMinutes": "Lightly Active Minutes",
                        "sedentaryMinutes": "Sedentary Minutes",
                        "veryActiveMinutes": "Very Active Minutes",
                        "sleep_duration": "Sleep Duration",
                        "sleep_efficiency": "Sleep Efficiency",
                        "restingHeartRate": "Resting Heart Rate",
                        "steps_count": "Steps Count"
                     })