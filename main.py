# APIFlask Python modules

from apiflask import APIFlask, APIBlueprint, Schema, HTTPError, abort
from apiflask.fields import Integer, Float, String, Boolean, DelimitedList
from apiflask.validators import Length, OneOf

# Flask Python modules

from flask import request, Response, render_template, stream_with_context
from flask_cors import CORS

# Standard Python modules

import os, datetime

# Custom Python modules

from modules.aws import get_public_ipv4
from modules.yolo_util import yolo_watch
from modules.post_processing import default_post_processing, bigquery_post_new_objects, trigger_post_url_new_objects, bigquery_post_and_trigger_new_objects, fps_annotator

# BIGQUERY SET UP ----------------

from google.cloud import bigquery

# set up the BigQuery client using the service account key file
credentials_path = 'auth/octacity-iduff.json'  # Replace with the path to your JSON with the path to your service account key file

# set up the dataset and table ids
dataset_id = 'video_analytics'  # Replace with your dataset ID
table_id = 'objetos_identificados'      # Replace with your table ID

# BigQuery client
bqclient = bigquery.Client.from_service_account_json(credentials_path)

# get the BigQuery client and table instances
# table_ref = bqclient.dataset(dataset_id).table(table_id)
# table = bqclient.get_table(table_ref)

# FLASK APP DEFINITION -----------------

# Set current API version
version = '0.1'

# set openapi.info.title and openapi.info.version
app = APIFlask(__name__, title='Octa Vision API', version=version, docs_ui='elements')
CORS(app)

# APP BLUEPRINTS -------------

object_bp = APIBlueprint('object', __name__, tag={'name': 'Objects', 'description': 'Objects detected or identified from camera image streams'})
camera_bp = APIBlueprint('camera', __name__, tag={'name': 'Cameras', 'description': 'Camera information'})


# OPENAPI SPECIFICATION OPTIONS --------------

# openapi.info.description
app.config['DESCRIPTION'] = open('README.MD').read()

# openapi.info.contact
app.config['CONTACT'] = {
    'name': 'OCTA CITY SOLUTIONS',
    'url': 'http://octacity.org',
    'email': 'luisresende@id.uff.br'
}

# openapi.info.license
# app.config['LICENSE'] = {
#     'name': 'MIT',
#     'url': 'https://opensource.org/licenses/MIT'
# }

# openapi.info.termsOfService
# app.config['TERMS_OF_SERVICE'] = 'http://example.com'

# openapi.tags
app.config['TAGS'] = [{
    'name': "Server",
    "description": "Server information"
}, {
    'name': "YOLO",
    "description": "Run Ultralytics YOLO inference"
},{
    'name': "Cameras",
    "description": "Registered cameras database"
},{
    'name': "Objects",
    "description": "Camera identified objects"
},{
    'name': 'Web Apps',
    'description': ''
},{
    'name': 'BigQuery',
    'description': ''
},{
    'name': 'Streaming',
    'description': ''
},{
    'name': 'Upload',
    'description': ''
}]

# openapi.servers
app.config['SERVERS'] = [{
    'name': 'Development Server',
    'url': 'http://localhost:5000'
},
{
    'name': 'Production Server',
    'url': 'http://api.example.com'
},
{
    'name': 'Testing Server',
    'url': 'http://test.example.com'
}]

# openapi.externalDocs
app.config['EXTERNAL_DOCS'] = {
    'description': 'Find more info here',
    'url': 'https://octacity.org'
}

# FLASK CONFIGURATION OPTIONS ----------------

# Flask timeout
app.config['TIMEOUT'] = None  # Set timeout to None (no timeout)


# SERVER INFO ENDPOINTS -----------

@app.get("/init")
@app.doc(tags=['Server'])
def initialize():
    name = os.environ.get("NAME", "Octa Vision API")
    return f'Server `{name}` version `v{version}` is running!'

@app.route("/teste", methods=["POST"])
@app.doc(tags=['Server'])
def test_server():
    data = request.json
    print(f'NOVO OBJETO: {data}')
    return data

@app.get("/ip")
@app.doc(tags=['Server'])
def server_ip():
    instance_id = 'i-01796a60ab18b8bd5'
    public_ipv4 = get_public_ipv4(instance_id)
    if 'ip' not in public_ipv4:
        message = "Failed to retrieve the public IPv4 address."
        print(message)
        raise HTTPError(500, message, public_ipv4['error'])
    print("Public IPv4 GET request successful:", public_ipv4['ip'])
    return public_ipv4['ip']


# ---
# WEB APPS

@app.get('/home')
@app.doc(tags=['Web Apps'])
def home():
    """Home
    
    Main menu and basic navigation
    """
    return render_template("home.html")

@app.get('/panel')
@app.doc(tags=['Web Apps'])
def cameras_app():
    """Panel
    
    Panel to registered cameras and visualize results in real time
    """
    return render_template("panel.html")

@app.get('/dashboard')
@app.doc(tags=['Web Apps'])
def cameras_list():
    """Cameras
    
    List of registered cameras
    """
    return render_template("inicio.html")

@app.get('/playground')
@app.doc(tags=['Web Apps'])
def yolo_playground():
    """Playground
    
    YOLO playground application to test and visualize inference results.
    """
    return render_template("playground.html")


# ---
# Ultralytics YOLO endpoints

# Metadata dictionary
metadata = {
    "source": {"title": "Video Source", "description": "The source of the video", "example": "http://example.com/video.mp4"},
    "post_url": {"title": "POST URL", "description": "The URL to send POST requests with results", "example": "http://api.example.com/test"},
    "post_scheme": {"title": "POST JSON", "description": "The schema of the JSON to send as the body of the POST request to `post_url` URL", "example": '{"TIPO": "objeto", "HORA": "hora", "URL": "url", "CONFIANCA": "confianca", "Chave1": "Valor1"}'},
    "model": {"title": "Model Name", "description": "The name of the ultralytics yolov8 model", "example": "yolov8s.pt"},
    "task": {"title": "Task", "description": "The ultralytics yolo task", "example": "track"},
    "max_frames": {"title": "Max Frames", "description": "Number of frames to capture", "example": 10},
    "seconds": {"title": "Seconds", "description": "Number of video seconds to capture", "example": 60},
    "execution_seconds": {"title": "Execution Seconds", "description": "Maximum execution time in seconds", "example": 300},
    "log_seconds": {"title": "Log Seconds", "description": "Time between logs in seconds. Set it to `None` to suppress logging", "example": 5},
    "fps": {"title": "FPS", "description": "Video frames per second to calculate video stream time", "example": 30},
    "process": {"title": "Process", "description": "Post-processing process", "example": "bigquery"},
    "annotator": {"title": "Annotator", "description": "Annotator type", "example": "fps"},
    "stream": {"title": "Stream", "description": "Whether to stream the results", "example": True},
    "objects": {"title": "Objects", "description": "List of objects", "example": "car, person, dog"},
    "classes": {"title": "Classes", "description": "List of classes", "example": "0, 1, 2"},
    "conf": {"title": "Confidence", "description": "Confidence threshold", "example": 0.5},
    "iou": {"title": "IOU", "description": "IOU threshold", "example": 0.5},
    "max_det": {"title": "Max Detections", "description": "Maximum number of detections", "example": 100},
    "vid_stride": {"title": "Video Stride", "description": "Video stride value", "example": 2},
    "imgsz": {"title": "Image Size", "description": "Image size", "example": 512},
    "device": {"title": "Device", "description": "Device type", "example": "cpu"},
    "tracker": {"title": "Tracker", "description": "Tracker type", "example": "botsort.yaml"},
    "persist": {"title": "Persist", "description": "Whether to persist the results", "example": True},
    "augment": {"title": "Augment", "description": "Whether to apply augmentation", "example": False},
    "save": {"title": "Save", "description": "Whether to save the results", "example": False},
    "show": {"title": "Show", "description": "Whether to show the results", "example": False},
    "verbose": {"title": "Verbose", "description": "Whether to display verbose output", "example": False}
}


class PredictIn(Schema):
    # Generate fields with metadata using the dictionary values
    source = String(required=True, metadata=metadata["source"])
    post_url = String(load_default=None, metadata=metadata["post_url"])
    post_scheme = String(load_default=None, metadata=metadata["post_scheme"])
    model = String(load_default="yolov8l.pt", validate=OneOf(["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt", "yolov8n-seg.pt", "yolov8s-seg.pt", "yolov8m-seg.pt", "yolov8l-seg.pt", "yolov8x-seg.pt", "yolov8n-pose.pt", "yolov8s-pose.pt", "yolov8m-pose.pt", "yolov8l-pose.pt", "yolov8x-pose.pt", ]), metadata=metadata["model"])
    task = String(load_default="predict", validate=OneOf(["predict", "track"]), metadata=metadata["task"])
    max_frames = Integer(load_default=None, metadata=metadata["max_frames"])
    seconds = Integer(load_default=None, metadata=metadata["seconds"])
    execution_seconds = Integer(load_default=None, metadata=metadata["execution_seconds"])
    log_seconds = Integer(load_default=10, metadata=metadata["log_seconds"])
    fps = Integer(load_default=3, metadata=metadata["fps"])
    process = String(load_default="none", validate=OneOf(["none", "console-log", "bigquery", "trigger", "bigquery-trigger"]), metadata=metadata["process"])
    annotator = String(load_default="none", validate=OneOf(["none", "fps"]), metadata=metadata["annotator"])
    stream = Boolean(load_default=False, metadata=metadata["stream"])
    objects = DelimitedList(String(), load_default=[], sep=[',', ', '], metadata=metadata["objects"])
    classes = DelimitedList(Integer(), load_default=[], sep=[',', ', '], metadata=metadata["classes"])
    conf = Float(load_default=0.3, metadata=metadata["conf"])
    iou = Float(load_default=0.7, metadata=metadata["iou"])
    max_det = Integer(load_default=300, metadata=metadata["max_det"])
    vid_stride = Integer(load_default=1, metadata=metadata["vid_stride"])
    imgsz = Integer(load_default=640, metadata=metadata["imgsz"])
    device = String(load_default="cpu", validate=OneOf(["cpu", "gpu"]), metadata=metadata["device"])
    tracker = String(load_default="botsort.yaml", validate=OneOf(["botsort.yaml", "bytetracker.yaml"]), metadata=metadata["tracker"])
    persist = Boolean(load_default=True, metadata=metadata["persist"])
    augment = Boolean(load_default=False, metadata=metadata["augment"])
    save = Boolean(load_default=False, metadata=metadata["save"])
    show = Boolean(load_default=False, metadata=metadata["show"])
    verbose = Boolean(load_default=False, metadata=metadata["verbose"])



post_processing_functions_dict = {
    'none': None,
    'console-log': default_post_processing,
    'bigquery': bigquery_post_new_objects,
    'trigger': trigger_post_url_new_objects,
    'bigquery-trigger': bigquery_post_and_trigger_new_objects,
}

annotators_dict = {
    'none': None,
    'fps': fps_annotator,
}

@app.get('/track')
@app.input(PredictIn, 'query')
@app.doc(tags=['YOLO'])
def yolo_predict(query):
    """YOLO inference

    Run YOLO inference on URL source.
    """

    device = query["device"]
    if device == "gpu":
        device = 0
    
    objects = None if len(query["objects"]) == 0 else query["objects"]
    classes = None if len(query["classes"]) == 0 else query["classes"]
            
    # Detection/tracking model parameters
    model_params = {
        "objects": objects,
        "classes": classes,
        "imgsz": query["imgsz"],
        "conf": query["conf"],
        "iou": query["iou"],
        "max_det": query["max_det"],
        "vid_stride": query["vid_stride"],
        "device": device,
        "tracker": query["tracker"],
        "persist": query["persist"],
        "augment": query["augment"],
        "save": query["save"],
        "show": query["show"],
        "verbose": query["verbose"],
    }
    
    post_processing_args_dict = {
        'none': None,
        'console-log': {},
        'bigquery': {
            'url': query['source']
        },
        'trigger': {
            'url': query['source'],
            'post_url': query['post_url'],
            'post_scheme': query['post_scheme']
        },
        'bigquery-trigger': {
            'url': query['source'],
            'post_url': query['post_url'],
            'post_scheme': query['post_scheme']
        },
    }

    post_processing_function = post_processing_functions_dict[query['process']]
    post_processing_args = post_processing_args_dict[query['process']]
    annotator = annotators_dict[query['annotator']]

    yolo_params_dict = {
        "source": query["source"],
        "model": query["model"],
        "task": query["task"],
        "model_params": model_params,
        "max_frames": query["max_frames"],
        "seconds": query["seconds"],
        "execution_seconds": query["execution_seconds"],
        "log_seconds": query["log_seconds"],
        "fps": query["fps"],
        "writer_params": None,
        "post_processing_function": post_processing_function,
        "post_processing_args": post_processing_args,
        "annotator": annotator,
        "generator": query["stream"]
    }
    
    print("INFERENCE REQUEST · QUERY ARGS:", query)
    print("YOLO PARAMETERS:", yolo_params_dict)
    
    results = yolo_watch(**yolo_params_dict)

    if query["stream"]:
        return Response(stream_with_context(results), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    return list(results)


@app.post('/track')
@app.input(PredictIn)
@app.doc(tags=['YOLO'])
def post_yolo_predict(data):
    """YOLO inference

    Run YOLO inference on URL source.
    """

    device = data["device"]
    if device == "gpu":
        device = 0
    
    objects = None if len(data["objects"]) == 0 else data["objects"]
    classes = None if len(data["classes"]) == 0 else data["classes"]
            
    # Detection/tracking model parameters
    model_params = {
        "objects": objects,
        "classes": classes,
        "imgsz": data["imgsz"],
        "conf": data["conf"],
        "iou": data["iou"],
        "max_det": data["max_det"],
        "vid_stride": data["vid_stride"],
        "device": device,
        "tracker": data["tracker"],
        "persist": data["persist"],
        "augment": data["augment"],
        "save": data["save"],
        "show": data["show"],
        "verbose": data["verbose"],
    }
    
    post_processing_args_dict = {
        'none': None,
        'console-log': {},
        'bigquery': {
            'url': data['source']
        },
        'trigger': {
            'url': data['source'],
            'post_url': data['post_url'],
            'post_scheme': data['post_scheme']
        },
        'bigquery-trigger': {
            'url': data['source'],
            'post_url': data['post_url'],
            'post_scheme': data['post_scheme']
        },
    }

    post_processing_function = post_processing_functions_dict[data['process']]
    post_processing_args = post_processing_args_dict[data['process']]
    annotator = annotators_dict[data['annotator']]

    yolo_params_dict = {
        "source": data["source"],
        "model": data["model"],
        "task": data["task"],
        "model_params": model_params,
        "max_frames": data["max_frames"],
        "seconds": data["seconds"],
        "execution_seconds": data["execution_seconds"],
        "log_seconds": data["log_seconds"],
        "fps": data["fps"],
        "writer_params": None,
        "post_processing_function": post_processing_function,
        "post_processing_args": post_processing_args,
        "annotator": annotator,
        "generator": data["stream"]
    }
    
    print("INFERENCE REQUEST · QUERY ARGS:", data)
    print("YOLO PARAMETERS:", yolo_params_dict)
    
    results = yolo_watch(**yolo_params_dict)
    
    if data["stream"]:
        return Response(stream_with_context(results), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    return  list(results)


# ---
# CAMERAS Bigquery DATABASE ENDPOINTS

class CameraIn(Schema):
    name = String(load_default='', metadata={'title': 'Camera Name', 'description': 'The unique camera name identifier.'})
    url = String(required=True, metadata={'title': 'Camera URL', 'description': 'The camera public IP URL.'})
    objects = DelimitedList(String(), sep=[',', ', '], load_default=[], metadata={'title': 'Objects', 'description': 'Comma delimited string list of objects.'})
    post_url = String(load_default='', metadata={'title': 'Post URL', 'description': 'URL to send POST requests from inference results.'})
    post_scheme = String(load_default='', metadata={'title': 'Post JSON Schema', 'description': 'JSON schema to send as the body of the POST request to `Post URL` from inference results.'})

class CameraOut(Schema):
    id = Integer(metadata={'title': 'Camera ID', 'description': 'The ID of the camera.'})
    # name = String(metadata={'title': 'Camera Name', 'description': 'The name of the camera.'})
    url = String(metadata={'title': 'Camera URL', 'description': 'The camera public IP URL.'})
    objects = String( metadata={'title': 'Objects', 'description': 'List of objects.'})
    post_url = String(metadata={'title': 'Post URL', 'description': 'URL to send POST requests from inference results.'})
    post_scheme = String(metadata={'title': 'Post JSON Schema', 'description': 'JSON schema to send as the body of the POST request to `Post URL` from inference results.'})
    timestamp = String(metadata={'title': 'Timestamp', 'description': 'The timestamp of when the camera was registered.'})



@app.get('/cameras')
@app.output(CameraOut(many=True), description='The list of registered cameras')
@app.doc(tags=['Cameras'])
def get_cameras():
    """Get All Cameras

    Get all cameras in the database.
    """
    try:
        # Fetch the list of cameras from the BigQuery database
        query = "SELECT *, ROW_NUMBER() OVER(ORDER BY timestamp) as id FROM `octacity.video_analytics.cameras`"
        query_job = bqclient.query(query)
        rows = query_job.result()
        cameras = [dict(row) for row in rows]
        return cameras

    except Exception as e:
        raise HTTPError(500, str(e))

@app.get('/cameras/<int:camera_id>')
@app.output(CameraOut, description='The camera with the given ID')
@app.doc(tags=['Cameras'])
def get_camera(camera_id):
    """Get a Camera

    Get a camera with a specific ID.
    """
    try:
        # Fetch the camera from the BigQuery database based on the provided camera_id
        query = f"SELECT * FROM (SELECT *, ROW_NUMBER() OVER(ORDER BY timestamp) as id FROM `octacity.video_analytics.cameras`) WHERE id = {camera_id}"
        query_job = bqclient.query(query)
        rows = query_job.result()

        camera = None
        for row in rows:
            camera = dict(row)
            
        if camera:
            return camera
        else:
            raise HTTPError(404, f'Camera with ID {camera_id} not found')

    except Exception as e:
        raise HTTPError(500, str(e))


@app.post('/cameras')
@app.input(CameraIn)
@app.doc(tags=['Cameras'])
@app.output(
    CameraOut,
    201,
    description='The camera you just created',
    links={'getCameraById': {
        'operationId': 'getCamera',
        'parameters': {
            'camera_id': '$response.body#/id'
        }
    }}
)
@app.doc(tags=['Cameras'])
def create_camera(data):
    """Create a Camera

    Create a camera with the given data. The created camera will be returned.
    """
    try:
        # Insert the camera data into the BigQuery database
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        objects = ', '.join([name.strip() for name in data['objects']])
        query = "INSERT INTO `octacity.video_analytics.cameras` (url, objects, post_url, post_scheme, timestamp) VALUES ('{}', '{}', '{}', '{}', '{}')".format(data['url'], objects, data['post_url'], data['post_scheme'], timestamp)
        query_job = bqclient.query(query)
        query_job.result()

        # Get the inserted camera ID
        query = 'SELECT ROW_NUMBER() OVER(ORDER BY timestamp) as id, * FROM `octacity.video_analytics.cameras` WHERE url = "{}"'.format(data['url'])
        query_job = bqclient.query(query)
        rows = query_job.result()

        camera_id = None
        for row in rows:
            camera_id = row['id']

        if camera_id is None:
            raise HTTPError(500, 'Failed to retrieve the ID of the created camera')

        # Create the response data
        response_data = dict(row)

        return response_data, 201

    except Exception as e:
        raise HTTPError(500, 'Failed to create camera', str(e))


@app.patch('/cameras/<int:camera_id>')
@app.input(CameraIn(partial=True))
@app.output(CameraOut, description='The updated camera')
@app.doc(tags=['Cameras'])
def update_camera(camera_id, data):
    """Update a Camera

    Update a camera with the given data.
    """
    try:
        # Check if the camera exists in the BigQuery database
        query = f"SELECT * FROM (SELECT *, ROW_NUMBER() OVER(ORDER BY timestamp) as id FROM `octacity.video_analytics.cameras`) WHERE id = {camera_id}"
        query_job = bqclient.query(query)
        rows = query_job.result()

        camera = None
        for row in rows:
            camera = dict(row)

        if not camera:
            raise HTTPError(404, f'Camera with ID {camera_id} not found')

        # Update the camera fields
        update_fields = []
        for field, value in data.items():
            if field in camera and value is not None:
                if field == 'objects':
                    value = ', '.join([name.strip() for name in value])
                camera[field] = value
                update_fields.append(f"{field} = '{value}'")

        # If no fields to update, return the existing camera
        if not update_fields:
            return camera

        # Perform the camera update in the BigQuery database
        query = 'UPDATE `octacity.video_analytics.cameras` SET {} WHERE url = "{}"'.format(", ".join(update_fields), camera['url'])
        query_job = bqclient.query(query)
        query_job.result()

        return camera

    except Exception as e:
        raise HTTPError(500, 'Failed to update the camera', str(e))


@app.delete('/cameras/<int:camera_id>')
@app.output({}, status_code=204, description='Empty')
@app.doc(tags=['Cameras'])
def delete_camera(camera_id):
    """Delete a Camera

    Delete a camera with specific ID.
    """
    try:
        # Fetch the camera from the BigQuery database based on the provided camera_id
        query = f"SELECT url FROM (SELECT *, ROW_NUMBER() OVER(ORDER BY timestamp) as id FROM `octacity.video_analytics.cameras`) WHERE id = {camera_id}"
        query_job = bqclient.query(query)
        rows = query_job.result()

        camera_url = None
        for row in rows:
            camera_url = row['url']

        if not camera_url:
            raise HTTPError(404, f'Camera with ID {camera_id} not found')

        # Delete the camera from the BigQuery database using its URL
        delete_query = f"DELETE FROM `octacity.video_analytics.cameras` WHERE url = '{camera_url}'"
        delete_job = bqclient.query(delete_query)
        delete_job.result()

        return ''

    except Exception as e:
        raise HTTPError(500, 'Failed to delete the camera', str(e))


# ---
# OBJECTS BigQuery DATABASE ENDPOINTS

class ObjectsIn(Schema):
    # id = String(load_default=None)
    url = String(load_default=None)

@app.get("/objects")
@app.input(ObjectsIn, "query")
@app.doc(tags=['Objects'])
def get_objects_from_bigquery(query):
    """
    Identified Objects
    Returns a JSON list of identified objects from the BigQuery table. Optionally filter by id or camera URL.
    """
    
    try:
        # Execute BigQuery query
        bq_query = f'SELECT ROW_NUMBER() OVER () AS id, * FROM `octacity.video_analytics.objetos_identificados`'
        if query['url'] is not None:
            bq_query += f' WHERE url = "{query["url"]}"'  # Add quotation marks around the URL value
        # if query['id'] is not None:
        #     bq_query = 'SELECT * FROM ({}) WHERE id = {}'.format(bq_query, query["id"])  # Add quotation marks around the URL value
        bq_query += ' ORDER BY timestamp DESC LIMIT 10'
        query_job = bqclient.query(bq_query)
        rows = query_job.result()

        # Convert the BigQuery result rows to a list of dictionaries
        result = [dict(row) for row in rows]

        return result

    except Exception as e:
        raise HTTPError(500, 'Failed to get objects', str(e))
        
class PetIn(Schema):
    name = String(
        required=True,
        validate=Length(0, 10),
        metadata={'title': 'Pet Name', 'description': 'The name of the pet.'}
    )
    category = String(
        required=True,
        validate=OneOf(['dog', 'cat']),
        metadata={'title': 'Pet Category', 'description': 'The category of the pet.'}
    )
    
class PetOut(Schema):
    id = Integer(metadata={'title': 'Pet ID', 'description': 'The ID of the pet.'})
    name = String(metadata={'title': 'Pet Name', 'description': 'The name of the pet.'})
    category = String(metadata={'title': 'Pet Category', 'description': 'The category of the pet.'})



# @app.get('/')
# @app.doc(tags=['Hello'])
# def say_hello():
#     """Just Say Hello

#     It will always return a greeting like this:
#     ```
#     {'message': 'Hello!'}
#     ```
#     """
#     return {'message': 'Hello!'}


# @app.get('/pets/<int:pet_id>')
# @app.output(PetOut, description='The pet with given ID')
# @app.doc(tags=['Pet'], operation_id='getPet')
# def get_pet(pet_id):
#     """Get a Pet

#     Get a pet with specific ID.
#     """
#     if pet_id > len(pets) - 1 or pets[pet_id].get('deleted'):
#         abort(404)
#     return pets[pet_id]


# @app.get('/pets')
# @app.output(PetOut(many=True), description='A list of pets')
# @app.doc(tags=['Pet'])
# def get_pets():
#     """Get All Pet

#     Get all pets in the database.
#     """
#     return pets


# @app.post('/pets')
# @app.input(PetIn)
# @app.output(
#     PetOut,
#     201,
#     description='The pet you just created',
#     links={'getPetById': {
#         'operationId': 'getPet',
#         'parameters': {
#             'pet_id': '$response.body#/id'
#         }
#     }}
# )
# @app.doc(tags=['Pet'])
# def create_pet(data):
#     """Create a Pet

#     Create a pet with given data. The created pet will be returned.
#     """
#     pet_id = len(pets)
#     data['id'] = pet_id
#     pets.append(data)
#     return pets[pet_id]


# @app.patch('/pets/<int:pet_id>')
# @app.input(PetIn(partial=True))
# @app.output(PetOut, description='The updated pet')
# @app.doc(tags=['Pet'])
# def update_pet(pet_id, data):
#     """Update a Pet

#     Update a pet with given data, the valid fields are `name` and `category`.
#     """
#     if pet_id > len(pets) - 1:
#         abort(404)
#     for attr, value in data.items():
#         pets[pet_id][attr] = value
#     return pets[pet_id]


# @app.delete('/pets/<int:pet_id>')
# @app.output({}, status_code=204, description='Empty')
# @app.doc(tags=['Pet'])
# def delete_pet(pet_id):
#     """Delete a Pet

#     Delete a pet with specific ID. The deleted pet will be renamed to `"Ghost"`.
#     """
#     if pet_id > len(pets) - 1:
#         abort(404)
#     pets[pet_id]['deleted'] = True
#     pets[pet_id]['name'] = 'Ghost'
#     return ''
