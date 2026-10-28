[ ] Phase1 - Patient portal

[x] Phase 1.1
### Goals
- Refer architecture in PRD.md and do the project setup.
- Add a simple landing page mentioning project name, refer `docs/UI_Design.md` for design.
- Setup a python fastapi backend.
- Add docker file, we will be running search engine through docker.
- for database, we will be using supabase free version.

### Done When
- A simple landing page with backend is setup with requiremnts, docker file.


[x] Phase 1.2
### Goals
- Add a `book_appointment` module in backend, the module is responsible for booking an appointment flow.
- Get the symptoms list from `https://www.kaggle.com/datasets/itachi9604/disease-symptom-description-dataset` and add clean list with weightage to supabase. This symptoms list will be shown in UI for patient.
- The patient comes and fill the symptoms form(Check UI_Design for the details). 
- Add a langraph for this booking flow.
- The natural language input from the patient has to be deidentified(removing the personal details like name, address, phone number... if any has added). This scrub will be one node in langraph.
- The selected responses and the cleaned natural language input from the patient has to fed to Jev model `typesafe/jev-1.13`(Via openrouter). This stage has to categorise the patient condition based on symptoms - Emergency, Severe, Normal.
- Write the system prompt for categorising based on the symptom weightage in the dataset and also refer `References/Categorise_symptom.txt`.
- Make sure the  list of symptoms we have added under different categories in the system prompt are added in a different json file and prompt uses the liost from json file. This helps to easy update of the symptoms.
- Add observability of this system in langsmith.
- Add clean and short dev docs for each business logic added.

### Done When
- Patient is able to select the symptoms and also add a natural language text. The system should be able to categorise the patient condition based on the symptoms.

[x] Phase 1.3
### Goals
- Now the book_appointment graph needs to take choice based on the emergency check done.
- Now the book_appointment graph needs to take choice based on the emergency check done.
- If the patient condition is emergency, Just end the graph logging 'An emergency condition. Will handle this condition in this application in later pahses.'
- If the condition is not emergency, Check for the specality of the doctor needed for this case. To identify the specality use Jev model with scores as we did for emergency check. Get the specalities list from database and fed it to the model for returning score for each specality.
- Once the specality is identified, check the doctors in that specality in doctors table and list down the slots available.
- If the case is Severe, Show the patient, 'Your condition is severe, choose some slot as earliest possible'. This slot suggestion engine should work in backend with pure logics(no AI) and patient should be able to select the doctor and slot.

### Done When
- If the condition is not emergency, patient should be able to select doctor and slot.


[x] Phase 1.4
### Goals
- Add the login page for patient
- After selecting the patient portal in landing page, ask for phone number first.
- If phone number is existing, get the details from database.
- If phone number is not existing in database, ask for patient details - name, age, gender(mandatory), location.
- For symptoms categorising(Emergency, Critical, Normal) get the age and gender from patient record and remove it from the symptoms form(about you section).
- Add the list of appointments of patient in the `My appointemnts` tab.

### Done When
- Patient has to login and add his details, this details are used for further model invocations for decisions and doctor suggestions.
- Patient has to see all his previous appointments.


[x] Phase 1.5
### Goals
- UI design has to be updated referring to `docs/Design/Doctor Portal - Screens`
- While suggesting doctors, use the location from patient profile for filtering doctors.

### Done When
- A new clean UI is visible and the doctors are filtered based on location and shown in UI.


[ ] Phase 1.6
### Goals
- Add a language detection and translation node before categorising symptoms.
- This step should translate all local language text to english.
- The existing workflow has different stages for severity and specality categorising, club them to one Jev model call. So for even emergency cases, the specality is already stored in database and can show in UI.

### Done Whwn
- Thes symptoms mentioned in mixed language like Hinglish, Tinglish should be identified.
- For emergency cases also, the specality should be shown in UI.


[x] Phase 2 - Consultation Scribe

[x] Phase 2.1
### Goals
- Add the login for doctor, similar to patient.
- Add flow for maintaining doctor digital signature. We can use local folder or AWS S3 for doing that.
- After login, doctor should see his today's appointments as defalut, Check the Doctor Portal section in `docs/UI_Design`.
- Check `docs/Design/Doctor Portal - Screens` for design and replicate the same design here.
- Doctor converation transcript can be stored in json format with proper file name identification and store them in s3 or local.

### Done When
- A doctor should be able to login, upload the digital signature, see his consultations, enter the consultation screen and start consultation and after consultation should see the transcript of his consversation with patient and can edit it.


[x] Phase 2.2
### Goals
- Fed the consultation transcript to LLM and get SOAP(Subjective, Objective, Assessment, Plan) response.
- Save SOAP summary.
- Get doctor approval on SOAP summary(through signature) and close consultation.
- Add langraph to handle all these stages and langsmith tracing for this graph.

### Done When
- The SOAP summary should be generated, saved. It should be viewed and allowed to edit by the doctor. After the doctor approval, the consulattaion has to be closed. 


[ ] Phase 3 - Pharmacist Portal
### Goals
- Data for pharmacy store.
- UI to view, update data on selling.


[ ] Phase 4 - Notification engine
### Goals
- Add a new notification sender module.
- Add handlers to send notification which can be used in multiple other modules for sending notifications.

### Done When
- Notifications can be send.

