
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

folder_id = "14IXHBDpExTdBDfh5GTKmQEIiv6AYHRMG"
creds = service_account.Credentials.from_service_account_file(
    'sa.json', scopes=['https://www.googleapis.com/auth/drive']
)
service = build('drive', 'v3', credentials=creds)

# Write a dummy file
with open('crud_test.txt', 'w') as f:
    f.write('This is a test file for live sync validation.')

file_metadata = {
    'name': 'crud_test.txt',
    'parents': [folder_id]
}
media = MediaFileUpload('crud_test.txt', mimetype='text/plain')
file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
print(f"File ID: {file.get('id')}")

# Save the ID for deleting it later
with open('test_file_id.txt', 'w') as f:
    f.write(file.get('id'))
