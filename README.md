# Central Repository System

## Overview

The Central Repository System is a web-based platform designed to efficiently store, manage, search, and retrieve academic and administrative data within an educational institution. The system serves as a centralized knowledge repository that enables students, teachers, and administrators to access relevant information quickly and accurately.

The platform combines advanced search capabilities, intelligent content summarization, and role-based administration to provide a seamless data management experience.

---

## Key Features

### 📚 Centralized Data Repository
- Stores various types of college-related data in a single platform.
- Provides efficient data organization and retrieval.
- Eliminates scattered information across multiple systems.

### 🔍 High-Performance Search Engine
- Powered by **Elasticsearch** for fast and scalable searching.
- Utilizes **Reverse Indexing** to significantly improve search performance.
- Enables rapid retrieval even from large datasets.

### ✨ Fuzzy Search Support
- Handles spelling mistakes and typographical errors.
- Uses fuzzy matching techniques to return relevant results even when search queries are inaccurate.
- Improves user experience and search accuracy.

### 🤖 AI-Powered Chatbot
- Integrated chatbot for content understanding and summarization.
- Generates concise summaries of stored documents and information.
- Helps users quickly understand large volumes of content.

### 👨‍💼 Administrative Management System
- Dedicated admin panel for managing repository content.
- User management and access control.
- Monitoring and maintenance of repository data.

### 👨‍🏫 Teacher–Student Relationship Management
- Maintains structured relationships between teachers and students.
- Facilitates academic record organization.
- Supports efficient access to educational data.

---

## Technology Stack

| Technology | Purpose |
|------------|----------|
| Python | Backend Development |
| Flask | Web Framework |
| Elasticsearch | Search & Indexing Engine |
| Docker | Containerization & Deployment |
| HTML | Frontend Structure |
| CSS | Frontend Styling |

---

## System Architecture

```text
User Request
      │
      ▼
 Flask Application
      │
      ├── Elasticsearch
      │      ├── Reverse Indexing
      │      └── Fuzzy Search
      │
      ├── Chatbot Module
      │      └── Content Summarization
      │
      └── Admin Management System
             └── Teacher-Student Data Management


## Setup and Run Instructions

Follow the steps below to set up and run the application:

1. Navigate to each project folder:

   ```bash
   cd <folder_name>
   ```

2. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the application:

   ```bash
   python app.py
   ```

4. Open your web browser and go to:

   ```
   http://localhost:5000
   ```

Repeat the above steps for each folder as needed.
