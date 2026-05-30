#!/usr/bin/env python3
import os
import sys
import json
import argparse
import io

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# Define required read-only access scope
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'

def authenticate():
    """Authenticates the user using Google OAuth 2.0.
    Caches token in token.json.
    """
    creds = None
    # Check if we already have a saved token
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"Warning: Failed to load existing token: {e}")
            creds = None

    # If no valid credentials, trigger authorization flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Token expired. Refreshing...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token: {e}")
                creds = None
        
        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"Error: Credentials file '{CREDENTIALS_FILE}' not found!")
                print("=========================================================================")
                print("Silakan ikuti instruksi di implementation_plan.md untuk membuat Client ID:")
                print("1. Buat proyek baru di Google Cloud Console")
                print("2. Aktifkan Google Drive API")
                print("3. Buat OAuth Client ID (Desktop Application)")
                print("4. Unduh berkas kredensial JSON dan simpan di folder ini dengan nama 'credentials.json'")
                print("=========================================================================")
                sys.exit(1)
                
            print("Memulai otentikasi OAuth 2.0. Silakan buka peramban Anda jika tidak terbuka secara otomatis...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save token for next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            print("Token berhasil disimpan di 'token.json'.")
            
    return creds

def list_files(service, query=None, limit=20):
    """Lists files in Google Drive, with optional search query."""
    try:
        q = "trashed = false"
        if query:
            # Escape single quotes in search query
            escaped_query = query.replace("'", "\\'")
            q += f" and name contains '{escaped_query}'"
            
        results = service.files().list(
            q=q,
            pageSize=limit,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime)"
        ).execute()
        items = results.get('files', [])

        if not items:
            print("Tidak ditemukan file di Google Drive.")
            return []
        
        print("\nDaftar File di Google Drive:")
        print(f"{'ID':<35} | {'Nama File':<40} | {'Mime Type':<35} | {'Tanggal Modifikasi'}")
        print("-" * 135)
        for item in items:
            modified = item.get('modifiedTime', 'N/A')
            # Shorten name if too long for display
            display_name = item['name']
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."
            
            # Shorten mimeType
            display_mime = item['mimeType']
            if len(display_mime) > 35:
                display_mime = display_mime[:32] + "..."
                
            print(f"{item['id']:<35} | {display_name:<40} | {display_mime:<35} | {modified}")
        return items
    except HttpError as error:
        print(f"Error saat memanggil Google API: {error}")
        return []

def download_file(service, file_id, output_path=None):
    """Downloads/exports a Google Drive file by ID."""
    try:
        # Get metadata
        file_metadata = service.files().get(fileId=file_id).execute()
        file_name = file_metadata['name']
        mime_type = file_metadata['mimeType']
        
        # Mappings for Google Workspace formats conversion
        google_conversions = {
            'application/vnd.google-apps.document': {
                'export_mime': 'text/plain',
                'ext': '.txt'
            },
            'application/vnd.google-apps.spreadsheet': {
                'export_mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'ext': '.xlsx'
            },
            'application/vnd.google-apps.presentation': {
                'export_mime': 'application/pdf',
                'ext': '.pdf'
            }
        }
        
        is_workspace = mime_type in google_conversions
        
        if is_workspace:
            conv_info = google_conversions[mime_type]
            export_mime = conv_info['export_mime']
            ext = conv_info['ext']
            
            if not output_path:
                base, _ = os.path.splitext(file_name)
                # Ensure no invalid characters in filename
                clean_base = "".join(c for c in base if c.isalnum() or c in (' ', '_', '-')).strip()
                output_path = clean_base + ext
                
            print(f"Mengekspor file Google Workspace '{file_name}' ke format '{export_mime}'...")
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            if not output_path:
                output_path = file_name
            print(f"Mengunduh file '{file_name}'...")
            request = service.files().get_media(fileId=file_id)
            
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                print(f"Progress Unduhan: {int(status.progress() * 100)}%")
                
        # Save locally
        with open(output_path, 'wb') as f:
            f.write(fh.getvalue())
        print(f"Berhasil mengunduh! File disimpan di: {os.path.abspath(output_path)}")
        return output_path
    except HttpError as error:
        print(f"Error saat mengunduh file: {error}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Utilitas Integrasi Google Drive API untuk Antigravity.")
    parser.add_argument("--list", action="store_true", help="Menampilkan daftar file dari Google Drive")
    parser.add_argument("--search", type=str, help="Mencari file berdasarkan nama di Google Drive")
    parser.add_argument("--download", type=str, help="Mengunduh file berdasarkan ID")
    parser.add_argument("--limit", type=int, default=20, help="Jumlah batas file yang ditampilkan (default: 20)")
    parser.add_argument("--output", type=str, help="Path khusus untuk menyimpan file yang diunduh")
    
    args = parser.parse_args()
    
    if not (args.list or args.search or args.download):
        parser.print_help()
        sys.exit(0)
        
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    
    if args.list:
        list_files(service, limit=args.limit)
    elif args.search:
        list_files(service, query=args.search, limit=args.limit)
    elif args.download:
        download_file(service, args.download, output_path=args.output)

if __name__ == "__main__":
    main()
