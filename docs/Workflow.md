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
- Also while suggesting doctors, use the location from patient profile for filtering doctors.
- Add the list of appointments of patient in the `My appointemnts` tab.

### Done When
- Patient has to login and add his details, this details are used for further model invocations for decisions and doctor suggestions.
- Patient has to see all his previous appointments.



[ ] Phase 2 - Notification handler

[ ] Phase 2.1
### Goals
- Add a new notification sender module.
- Add handlers to send notification which can be used in multiple other modules for sending notifications.

### Done When
- Notifications can be send.