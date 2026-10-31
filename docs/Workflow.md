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


[x] Phase 1.6
### Goals
- Interpret multilingual symptoms directly in the combined Jev classification call (updated: no separate translation model call).
- Return severity and specialty decisions from the original de-identified text; translated text does not need to be generated or stored.
- The existing workflow has different stages for severity and specality categorising, club them to one Jev model call. So for even emergency cases, the specality is already stored in database and can show in UI.
- Add profile UI for patient portal. On clicking the profile icon on the top-right corner, show a popup with all patient details stored where patient can edit few editable fields like location, name.

### Done Whwn
- Thes symptoms mentioned in mixed language like Hinglish, Tinglish should be identified.
- For emergency cases also, the specality should be shown in UI.
- A patient can see the profile popup on clicking the profile icon in the top-right corner, where the editable patient details can be edited.


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



[x] Phase 3 - Data ingestion
### Goals
- The current data has multiple symptoms, multiple specalities. I wanted only few good specalities and cover all symptoms from mild to severe symptoms related to that specality listed in the symptoms list.
- The specalities I wanted is - Cardiology, Orthopedics, Dermatology, gaestroentrology.
- I have added symptoms data to `data/symptoms_2.json`. This list also connects severity to each symptom, so no need to new symptom_categories data. Clearly understand the symptoms_2.json and update both frontend and the backend model to use this data for severity check.
- In appointments flow, make symptoms dropdown input as optional, patient can only enter the natual language text without selecting the symptom.
- In appointement table, the patient written symptoms is added under history field, the field name is mis communicating the data stored. So, update the field name.
- The legacy_consultation_id, allergies, vitals fields also looks irrelevant in the appointment table. So, remove those fields
- Add the specality field in the appointemnts which can be null also, When the first symptoms categorisation done, this field can be filled(Use joins from the specalities table)
- Remove all the appointments, consultations data as it will not suit for existing new symptoms data.

### Done When
- The new symptoms data has to be reflected in the application. 
- The database tables data cleaning and the appointmet table updates should be done.



[x] Phase 4 - Pharmacist Portal

[x] Phase 4.1 - Data ingestion
### Goals
- Check the data in `pharmacy/data/medicines.json` and maintain the clean pharmacy data in postgres along with stock.
- Show the stock UI in pharmacist portal with filters - brands, specality, compositions, stock.
- Do simple login for pharmacist as we did for doctors, no authentication flow needed now.
- Add two tabs in UI - 1. To view the stock with fiters. 2. The signed doctor consultations, where patient will reach pharmacy soon.

### Done When
- The medicines data is stored and the pharmacist portal shows the list with filters.


[x] Phase 4.2
### Goals
- After SOAP generation, doctor should prescribe medicines. Doctor should select medicines from the list. 
- Add filters like specality(based on doctors's profile) for fetching the medicines to show in UI which doctor selects.
- Check the docs/Design folder for the doctor consultation screen's medicines UI.
- Add this medicines prescription as a new node in the consultation graph.
- The UI for the SOAP is not as per design `docs\Design\4. Doctor Consultation, listening, transcript, SOAP.png`, Fix the Ui for displaying SOAP.

### Done When
- In consultation screen, the SOAP UI is updated and the doctor can see the medicines suggested and can edit, add or remove the medicines and then sign the consultation.


[x] Phase 4.3
### Goals
- Once the doctor prescribed the medicine and signed the consultation. The stock has to be locked for that consultation. Maintain the locked count column in the medicines table in database.
- Pharmacist can check the closed consultation and if the patient did not come for medicines, he can unlock the stock after 24 hours. In UI show the red flag kind of thing, saying the consultation finished yesterday and stock is locked, but patient did not got the medicines.

### Done When
- The automatic lock for medicines on consultation.
- The pharmacist can unlock the stock locked.



[ ] Phase 5 - Memory
### Goal
- Add the langragph checkpointer for every consulatation as there are high chances that doctor speaks stops and then again may start speaking where the thread is same but some operations are happening again. Doctor may wait for some time to get some test like blood test or X-Ray done and then speaks and the generates SOAP. So maintain the check pointer for this. We are adding the converstaion to S3


[ ] Phase 6 - Notification engine
### Goals
- Add a new notification sender module.
- Add handlers to send notification which can be used in multiple other modules for sending notifications.

### Done When
- Notifications can be send.

