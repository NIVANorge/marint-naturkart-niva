#!/bin/bash
pip install xdem 
pip install --upgrade xgboost==3.2.0

papermill notebooks/02_modelling.ipynb notebooks/02_modelling_output.ipynb
