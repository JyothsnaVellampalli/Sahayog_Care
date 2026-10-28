## Rules
- The UI should be responsive and mobile friendly.
- All the accessibility web standards should be met.
- Every screen should have the router path.
- Maintain a global styles files with the current color and font theme.
- Errors, suceess, info has to be clearly communicated with proper text, colors, animations.
- Follow the same color and font patters across all screens.
- If the data is not ready for any screen, show the clean `Under Construction` instead of blocking the page.\


## Landing page 
- A blank page with a profile selector - Patient, Doctor, Front desk
- The UI should look similar to google chrome asking to select a profile while launching.

## Patient portal
- On clicking the patient in the landing page, a patient portal has to be shown
- It should has a header with patient profile (name) in the right corner and the Sahayog Care in the left end
- The patient portal should have three nav items - Book an appointment(default nav option), My appointements

## Patient portal - Book an appointment
- Add a form for adding symptoms.
- Form should have a dropdown with multi-select to select sympotoms in the first row.
- Once the symptoms are selected - show the symptoms details form below the symptoms dropdown.
- Each symptom should be in a row asking for severity and duration and a button to remove the symptom.
- After all the symptom details forms are filled, add a input box where the patient can add more detail if needed.

## Patient portal - My appointements
- This is the list of appointements with date, doctor, disease in a tabular format.
- On selecting any of the row, a appointment page will be opened - has the detailed symptoms input, consultaion, medicines, summary.

## Doctor Portal
- On clicking doctor in the landing page, a doctor portal has to be shown
- The header should be similar to the patient portal header
- In the doctor portal, if there is no digital signature uploaded, ask for it. Without digital signature ready, doctor can not enter the consulation screen.

## Doctor Portal - Consulations list
- The portal all the doctor consultations with data and time filters, default to today filter.
- Each consultation block should show the data-time, status of the consultation and the case severity with symptoms the patient mentioned.
- On clicking the consultation block, it should redirect to a new consultation page.

## Doctor Portal - Consultation view
- The consultation view should show full details in the top with all patient details, symptoms and make this section collapsible to thge top.
- At the center of the screen show a good visible speech icon which doctor clicks before starting consultation.
- The speech UI should show some heatbeat kind of animation to show the listening state.
- After the consultation ends, doctor clicks on the listening state animation which should stop the listening.
- Now the transcript section should be shown with clear converstaion happened between doctor and patient.
- The speech icon shouls available at the top-right corner of the transcription block.
- On speaking again, the same listening animation should show and stopping should appends the transcription to the existing one.
- Doctor should be able to edit the transcript.
- This transcription should also be in collapsible state.
- LLM processes the transcript and gives some summary, add that in the next section as `SOAP`.