import os
from urllib.parse import urlencode
from os import environ
from flask import Flask, request, jsonify, abort, render_template, Response, flash, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from .models import db

from .ivr import ivr
from .wearable import wearable
from .portal import portal
from dotenv import load_dotenv
load_dotenv()

def create_app():
    #app = Flask(__name__)
    #app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    #app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    #Setup FLASK App
    app = Flask(
        __name__,
        template_folder='../templates', 
        static_folder='../static')
    sqlite_db_path = os.path.join(
        os.path.dirname(os.path.abspath(os.path.dirname(__file__))),
        os.getenv('SQLITE_DB_PATH')
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{sqlite_db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    
    migrate = Migrate(app, db)
    app.secret_key = os.getenv('SQLITE_DB_PATH')
    
    # CORS Configuration
    CORS(
        app,
        origins=["https://abdullahikawu.org", "https://*.abdullahikawu.org"]
    )
    # Register Blueprints
    app.register_blueprint(ivr, url_prefix='/ivr')
    app.register_blueprint(wearable, url_prefix='/wearable')
    app.register_blueprint(portal, url_prefix='/portal')
    
    with app.app_context():
        db.create_all()
    
    return app