from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()

class ApplicationData(db.Model):
    __tablename__ = 'application_data'
    application_data_id = db.Column(db.Integer, primary_key=True)
    fitbit_client_id = db.Column(db.String(255), nullable=False)
    fitbit_secret = db.Column(db.String(255), nullable=False)
    fhir_server_url = db.Column(db.String(255), nullable=False)
    
    def __repr__(self):
        return f'<ApplicationData {self.application_data_id}>'

class EHRSystem(db.Model):
    __tablename__ = 'ehr_system'
    ehr_system_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    base_link = db.Column(db.String(255), nullable=True)
    api_link = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<EHRSystem {self.name}>'

class Identity(db.Model):
    __tablename__ = 'identity'
    identity_id = db.Column(db.Integer, primary_key=True)
    practitioner_id = db.Column(db.Integer, db.ForeignKey('practitioner.practitioner_id'), nullable=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.patient_id'), nullable=True)
    ehr_system_id = db.Column(db.Integer, db.ForeignKey('ehr_system.ehr_system_id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.organization_id', name='fk_identity_organization_id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    auth_session = db.relationship('AuthSession', back_populates='identity')
    organization = db.relationship('Organization', back_populates='identity')
    practitioner = db.relationship('Practitioner', back_populates='identity')
    patient = db.relationship('Patient', back_populates='identity')
    ehr_system = db.relationship('EHRSystem')
    request = db.relationship('Request', back_populates='identity', uselist=False)

    def __repr__(self):
        return f'<Identity {self.identity_id}>'

class Patient(db.Model):
    __tablename__ = 'patient'
    patient_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(15), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    auth_session = db.relationship('AuthSession', back_populates='patient', uselist=False)
    identity = db.relationship('Identity', back_populates='patient', uselist=False)
    fitbit_data = db.relationship('Fitbit', back_populates='patient', uselist=False)

    def __repr__(self):
        return f'<Patient {self.name}>'

class Practitioner(db.Model):
    __tablename__ = 'practitioner'
    practitioner_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(15), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    identity = db.relationship('Identity', back_populates='practitioner', uselist=False)

    def __repr__(self):
        return f'<Patient {self.name}>'

class Fitbit(db.Model):
    __tablename__ = 'fitbit'
    fitbit_id = db.Column(db.Integer, primary_key=True)
    access_token = db.Column(db.String(255), nullable=False)
    refresh_token = db.Column(db.String(255), nullable=False)
    refresh_time = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.patient_id'), nullable=False)

    patient = db.relationship('Patient', back_populates='fitbit_data')

    def __repr__(self):
        return f'<Fitbit {self.fitbit_id}>'

class Request(db.Model):
    __tablename__ = 'request'
    request_id = db.Column(db.Integer, primary_key=True)
    identity_id = db.Column(db.Integer, db.ForeignKey('identity.identity_id'), nullable=False)
    startedAtTime = db.Column(db.DateTime(timezone=True), nullable=True)
    endedAtTime = db.Column(db.DateTime(timezone=True), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    rdf_file = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    identity = db.relationship('Identity', back_populates='request')

    def __repr__(self):
        return f'<Request {self.request_id}>'

class CallSession(db.Model):
    __tablename__ = "call_session"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), nullable=False)
    validated = db.Column(db.Boolean, nullable=True, default=False)
    practitioner_id = db.Column(db.String(50), nullable=True)
    patient_id = db.Column(db.String(50), nullable=True)
    data = db.Column(db.JSON, nullable=False)
    phone_number = db.Column(db.String(15), nullable=True)
    rdf_file = db.Column(db.String(255), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f'<session id: {self.session_id}>'

class AuthSession(db.Model):
    __tablename__ = "auth_session"
    auth_session_id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(255), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.patient_id'), nullable=False)
    identity_id = db.Column(db.Integer, db.ForeignKey('identity.identity_id'), nullable=True)
    data = db.Column(db.JSON, nullable=True)
    code_verifier = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    
    patient = db.relationship('Patient', back_populates='auth_session')
    identity = db.relationship('Identity', back_populates='auth_session')

    def __repr__(self):
        return f'<patient: {self.patient_id}, state: {self.state}>'

class Organization(db.Model):
    __tablename__ = 'organization'
    organization_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    org_id = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    identity = db.relationship('Identity', back_populates='organization', uselist=False)
    def __repr__(self):
        return f'<Organization: {self.name}>'