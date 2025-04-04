from flask import Flask, request, jsonify
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta, timezone  # Updated import
import os
import mimetypes
from io import BytesIO
from PIL import Image  # For thumbnail generation

app = Flask(__name__)

# Azure Blob Storage Configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING_1')
CONTAINER_NAME = "weez-cloud-data"
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

# Helper function to get blob client
def get_blob_client(email, filename):
    blob_name = f"{email}/{filename}"
    return blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_name)

# Upload a file
@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        email = request.form['email']
        file = request.files['file']
        filename = file.filename

        blob_client = get_blob_client(email, filename)
        blob_client.upload_blob(file, overwrite=True)

        # Store metadata (e.g., upload date)
        blob_client.set_blob_metadata({"upload_date": datetime.now(timezone.utc).isoformat()})

        return jsonify({"message": f"File {filename} uploaded successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Delete a file
@app.route('/delete', methods=['POST'])
def delete_file():
    try:
        email = request.json['email']
        filename = request.json['filename']

        blob_client = get_blob_client(email, filename)
        blob_client.delete_blob()

        return jsonify({"message": f"File {filename} deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# List files with metadata
@app.route('/list', methods=['GET'])
def list_files():
    try:
        email = request.args.get('email')
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/", include=['metadata'])
        file_list = [
            {
                "name": blob.name.split('/')[1],
                "size": blob.size,
                "upload_date": blob.metadata.get("upload_date", ""),
                "mime_type": mimetypes.guess_type(blob.name.split('/')[1])[0] or "application/octet-stream",
                "starred": blob.metadata.get("starred", "false") == "true"
            }
            for blob in blobs
        ]
        return jsonify({"files": file_list}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Generate SAS URL (for download/share/preview)
@app.route('/generate-sas', methods=['POST'])
def generate_sas():
    try:
        email = request.json['email']
        filename = request.json['filename']
        duration = int(request.json.get('duration', 1))  # Default 1 hour

        blob_client = get_blob_client(email, filename)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=f"{email}/{filename}",
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=duration)
        )
        sas_url = f"{blob_client.url}?{sas_token}"

        return jsonify({"sas_url": sas_url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Generate thumbnail for preview
@app.route('/thumbnail', methods=['POST'])
def generate_thumbnail():
    try:
        email = request.json['email']
        filename = request.json['filename']
        blob_client = get_blob_client(email, filename)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        if mime_type.startswith('image'):
            blob_data = blob_client.download_blob().readall()
            img = Image.open(BytesIO(blob_data))
            img.thumbnail((100, 100))  # Thumbnail size
            output = BytesIO()
            img.save(output, format="PNG")
            thumbnail_data = output.getvalue()
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=CONTAINER_NAME,
                blob_name=f"{email}/thumbnails/{filename}.png",
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(hours=1)
            )
            thumbnail_client = get_blob_client(email, f"thumbnails/{filename}.png")
            thumbnail_client.upload_blob(thumbnail_data, overwrite=True)
            return jsonify({"thumbnail_url": f"{thumbnail_client.url}?{sas_token}"}), 200
        return jsonify({"message": "No thumbnail available"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Search files
@app.route('/search', methods=['GET'])
def search_files():
    try:
        email = request.args.get('email')
        query = request.args.get('query', '').lower()
        type_filter = request.args.get('type', '')
        date_filter = request.args.get('date', '')

        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/", include=['metadata'])
        file_list = [
            {
                "name": blob.name.split('/')[1],
                "size": blob.size,
                "upload_date": blob.metadata.get("upload_date", ""),
                "mime_type": mimetypes.guess_type(blob.name.split('/')[1])[0] or "application/octet-stream",
                "starred": blob.metadata.get("starred", "false") == "true"
            }
            for blob in blobs
        ]

        filtered_files = [
            f for f in file_list
            if (query in f["name"].lower() or not query) and
               (type_filter in f["mime_type"] or not type_filter) and
               (date_filter in f["upload_date"] or not date_filter)
        ]
        return jsonify({"files": filtered_files}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Toggle starred status
@app.route('/star', methods=['POST'])
def star_file():
    try:
        email = request.json['email']
        filename = request.json['filename']
        starred = request.json['starred']

        blob_client = get_blob_client(email, filename)
        metadata = blob_client.get_blob_metadata()
        metadata["starred"] = "true" if starred else "false"
        blob_client.set_blob_metadata(metadata)

        return jsonify({"message": f"File {filename} starred status updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Get storage usage
@app.route('/storage-usage', methods=['GET'])
def storage_usage():
    try:
        email = request.args.get('email')
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/")
        total_size = sum(blob.size for blob in blobs) / (1024 * 1024)  # Size in MB
        return jsonify({"usage_mb": total_size}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
