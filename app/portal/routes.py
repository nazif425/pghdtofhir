from . import portal
from flask import g, Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from sqlalchemy.sql import func
from ..models import db, CallSession, ApplicationData, EHRSystem, Identity, Organization
from ..models import Patient, Practitioner, Fitbit, Request, AuthSession
from dotenv import load_dotenv

load_dotenv()
TRIPLESTORE_URL = os.getenv('TRIPLESTORE_URL')

@portal.route('/query', methods=['GET', 'POST'])
def data_query():
    if request.method == 'GET':
        return render_template('query.html')

    elif request.method == 'POST':
        query = request.data.decode('utf-8')  # Get SPARQL query from frontend

        # Send query to Fuseki
        headers = {
            'Accept': 'application/sparql-results+json',
            'Content-Type': 'application/sparql-query'
        }
        try:
            response = requests.post(TRIPLESTORE_URL + "/query", data=query, headers=headers)
            return jsonify(response.json()), response.status_code
        except requests.exceptions.RequestException as e:
            return jsonify({"error": str(e)}), 500

@portal.route('/ehr', methods=['POST', 'GET'])
def add_ehr_system():
    if not session.get('practitioner_id', None):
        return redirect(url_for('portal.practitioner_login'))
    
    if request.method == "POST":
        name = request.form['name']
        api_link = request.form['api_link']
        base_link = request.form['base_link']
        
        # validate name
        if not name: #or not api_link or not base_link
            flash('Name field is required.', 'danger')
            return redirect(request.url)
        
        # Create new Identity instance
        new_ehrsystem = EHRSystem(
            name=name,
            api_link=api_link,
            base_link=base_link)
        
        db.session.add(new_ehrsystem)
        
        db.session.commit()
        flash('EHR added successfully', 'success')
        return redirect(request.url)  # Redirect back to the form
    # GET request: Render the registration form with EHR systems
    return render_template('add_ehr_system.html')

# Registration page for practitioner
@portal.route('/practitioner', methods=['POST', 'GET'])
def create_practitioner():
    if request.method == 'POST':
        email = request.form['email']
        phone = request.form['phone_number']
        name = request.form['name']
        user_id = request.form['practitioner_id']
        code = request.form['code']
        
        # Validate inputs here if necessary
        if not email or not name or not phone or not code or not user_id:
            flash('All fields are required.', 'danger')
            return redirect(request.url)
        
        # verify code
        if code != "1234":
            flash('Invalid referral code.', 'danger')
            return redirect(request.url)
        
        # verify if email exist
        practitioner = Practitioner.query.filter_by(email=email).first()
        if practitioner:
            flash('Email already exist.', 'danger')
            return redirect(request.url)
        
        # Create new practitioner instance
        # print(practitioner.query.delete())
        new_practitioner = Practitioner(name=name, email=email, phone_number=phone, user_id=user_id)
        db.session.add(new_practitioner)
        db.session.commit()
        
        flash('Registration successful!', 'success')
        
        #return render_template('practitioner_registration.html')
        return redirect(url_for('portal.practitioner_login'))  # Redirect to a success page or back to the form
    
    # GET request: Render the registration form
    return render_template('practitioner_registration.html')

# Practitioner login page
@portal.route('/practitioner_login', methods=['GET', 'POST'])
def practitioner_login():
    
    if request.method != 'POST':
        return render_template('practitioner_login.html')

    email = request.form['email']
    if email is None:
        flash(f'Please enter email to continue', 'error')
        return render_template('practitioner_login.html')
    
    practitioner = Practitioner.query.filter_by(email=email).first()
    if not practitioner:
        flash(f'the email {email} not found', 'error')
        return render_template('practitioner_login.html')
    
    session['practitioner_id'] = practitioner.practitioner_id
    flash('Login successful!', 'success')
    
    #return render_template('practitioner_login.html')
    return redirect(url_for('portal.practitioner_dashboard'))

@portal.route('/practitioner/edit', methods=['POST', 'PUT', 'GET'])
def update_practitioner():
    # verify practitioner access
    if not session.get('practitioner_id', None):
        return redirect(url_for('portal.practitioner_login'))
    
    practitioner = Practitioner.query.get_or_404(session.get('practitioner_id', None))
    
    if request.method == 'POST':
        # Handle the POST request (form submission)
        practitioner.name = request.form['name']
        practitioner.user_id = request.form['practitioner_id']
        practitioner.phone_number = request.form['phone_number']
        practitioner.email = request.form['email']
        db.session.commit()
        flash('Practitioner profile updated successfully!', 'success')
        #return redirect(url_for('portal.update_practitioner', practitioner=practitioner))
    return render_template('update_practitioner.html', practitioner=practitioner)

@portal.route('/practitioner/dashboard', methods=['GET'])
def practitioner_dashboard():
    # verify practitioner access
    if not session.get('practitioner_id', None):
        return redirect(url_for('portal.practitioner_login'))
    
    practitioner = Practitioner.query.get_or_404(session.get('practitioner_id', None))
    
    return render_template(
        'practitioner_dashboard.html',
        practitioner=practitioner)

@portal.route('/practitioner/requests', methods=['GET'])
def practitioner_requests():
    # verify practitioner access
    if not session.get('practitioner_id', None):
        return redirect(url_for('portal.practitioner_login'))
    
    practitioner_id = session.get('practitioner_id', None)
    practitioner = Practitioner.query.get_or_404(practitioner_id)
    
    identityList = Identity.query.filter_by(practitioner_id=practitioner_id).all()
    current_id = 0
    table_data = []
    if len(identityList) > 0:
        for identity in identityList:
            current_id += 1
            record = {}
            patient = identity.patient
            fitbit_entry = Fitbit.query.filter_by(patient_id=patient.patient_id).first()
            
            record['id'] = current_id
            record['name'] = patient.name
            record['email'] = patient.email
            record['patient_id'] = patient.user_id
            record['ehr'] = identity.ehr_system.name
            record['access'] = True if fitbit_entry else False 
            if record['access']:
                record['request'] = '<a href="/wearable/fetch_fitbit_data?id={}">Fetch data </a>'.format(identity.identity_id)
            else:
                record['request'] = ''
            table_data.append(record)
    print(table_data)
    return jsonify({
        "table_data": table_data,
    })

@portal.route('/practitioner_logout', methods=['GET'])
def practitioner_logout():
    del session['practitioner_id']
    flash('Logout successful!', 'success')
    return redirect(url_for('portal.practitioner_login'))

@portal.route('/patient_logout', methods=['GET'])
def patient_logout():
    del session['patient_id']
    flash('Logout successful!', 'success')
    return redirect(url_for('portal.patient_login'))

@portal.route('/patient', methods=['POST', 'GET'])
def create_patient():
    # verify practitioner access
    if not session.get('practitioner_id', None):
        return redirect(url_for('portal.practitioner_login'))
    
    if request.method == 'POST':
        email = request.form['email']
        ehr_system_id = request.form['ehr_system_id']
        patient_id = request.form['patient_id']

        # Validate inputs
        if not email or not ehr_system_id or not patient_id or not practitioner_id:
            flash('All fields are required.', 'danger')
            return redirect(request.url)
        
        # Verify if a patient exist with the email
        patient = Patient.query.filter_by(email=email).first()
        
        if patient is None:
            # create a new patient record
            patient = Patient(user_id=patient_id) # No name for now
            db.session.add(patient)
            db.session.flush() # To get the patient_id
        
        # fetch practitioner record
        practitioner = Practitioner.query.get_or_404(session.get('practitioner_id', None))
        
        # Create new Identity instance
        new_identity = Identity(patient_id=patient.patient_id,
                                ehr_system_id=ehr_system_id,
                                practitioner_id=practitioner.practitioner_id)
        db.session.add(new_identity)
        
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('portal.patient_login'))  # Redirect to a success page or back to the form
    
    # GET request: Render the registration form with EHR systems
    ehr_systems = EHRSystem.query.all()
    return render_template('patient_registration.html', ehr_systems=ehr_systems)

@portal.route('/patient_login', methods=['GET', 'POST'])
def patient_login():
    
    if request.method != 'POST':
        return render_template('patient_login.html')

    email = request.form['email']
    if email is None:
        flash(f'Please enter email to continue', 'error')
        return render_template('patient_login.html')
    
    patient = Patient.query.filter_by(email=email).first()
    if patient is None:
        flash(f'the email {email} not found', 'error')
        return render_template('patient_login.html')
    
    session['patient_id'] = patient.patient_id
    
    if not patient.name:
        return redirect(url_for('portal.update_patient'))
    return redirect(url_for('portal.patient_dashboard'))

@portal.route('/patient/edit', methods=['POST', 'PUT', 'GET'])
def update_patient():
    # verify patient access
    if not session.get('patient_id', None):
        return redirect(url_for('portal.patient_login'))
    
    patient = Patient.query.get_or_404(session.get('patient_id', None))
    if request.method == 'POST':
        # Handle the POST request (form submission)
        patient.name = request.form['name']
        patient.phone_number = request.form['phone_number']
        db.session.commit()
        flash('Patient profile updated successfully!', 'success')
        return redirect(url_for('portal.update_patient'))
    return render_template('update_patient.html', patient=patient)

@portal.route('/patient/dashboard', methods=['GET'])
def patient_dashboard():
    if not session.get('patient_id', None):
        return redirect(url_for('portal.patient_login'))
    
    patient = Patient.query.get_or_404(session.get('patient_id', None))
    
    fitbit_entry = Fitbit.query.filter_by(patient_id=patient.patient_id).first()
    fitbit_connected = False
    if fitbit_entry:
       fitbit_connected = True
    return render_template(
        'patient_dashboard.html',
        patient=patient,
        fitbit_connected=fitbit_connected,
        connect_fitbit_link=url_for('wearable.request_authorization'),
        disconnect_fitbit_link=url_for('wearable.cancel_authorization'))
