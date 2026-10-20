# What JuStAI5 can do – examples to try

*[Deutsch](de/BEISPIELE.md) · English*

Every conversation starts with **"Hey Jarvis"**. Then just talk normally; follow-up
questions need no new wakeword. Saying "Hey Jarvis" again within 5 minutes continues the
conversation ("And how many people live there?"). Everything also works typed:
*Conversations* in the interface.

The assistant understands and answers in English, German and Italian, always in the
language it was spoken to.

Answers always come in the room where the question was asked, never anywhere else, unless
you explicitly ask for it.

✔ = tried with real hardware or in the automatic tests. In brackets: what is needed.

## Reminders when it sees you

* "The next time you see me from tomorrow 9 am, remind me to take out the rubbish." ✔
  *(face registered)*
  Creates a one-time rule that is only armed from tomorrow 9:00. The assistant speaks to
  you as soon as a camera recognises you afterwards, and you can answer right away.
* "The next time you see Anna, greet her by name." ✔
* "When I come home, tell me what the weather will be like tomorrow."
  *("coming home" = not seen for at least an hour)*
* "If you see Lukas after 10 pm, tell him to go to bed."
* "Every time you see me in the kitchen, remind me to drink something."

Without further details "the next time" only counts after at least 10 minutes of absence.
Otherwise the greeting would start while you are sitting in front of the camera anyway.

## Scheduled

* "Remind me of the dentist appointment tomorrow at 7:30." ✔
* "Remind me in a quarter of an hour to switch on the dryer." ✔ *(said exactly once)*
* "Tell me the weather every working day at 7 am here in the bathroom."
* "Remind me every Sunday evening at 8 pm to put out the bin."
* "Which reminders do you have for me?" · "Delete the dentist reminder." *(asks before
  deleting)*

## Searching and finding

* "Where are my car keys? Search the pool house." ✔ *(pan/tilt camera, Gemini)*
  The camera sweeps the whole room (10 viewing directions, also downwards), searches all
  images and stops on the find: "On the table to the left of the laptop."
* "Look for my glasses in the living room."
* "Where is Lucky?" *(Lucky created as a pet with species `dog` or `cat`)*
  Answer from the camera sightings: "Last seen in the garden, 12 minutes ago."
* "Where did you last see Julian?"
* "Is anybody in the garden right now?" · "How many people are in the living room?"
  *(local, no cloud)*

## Looking

* "What do you see right now?" *(Gemini)*
* "Is the front door open?" · "Is the light still on in the garage?"
* "Is my phone on the desk?"
* "Read out what is written on the note on the fridge."
* "Follow me with the camera." · "Look left." · "Camera back to the home position."
  *(pan/tilt camera)*

What goes to Google and what stays local can be set per room ([AI.md](AI.md)).

## Watching and telling you

* "Tell me when a car drives into the driveway."
* "Let me know when the dog goes into the garden."
* "Watch until tonight whether somebody comes to the garden gate."
* Learning states: "Remember, this is what the garage door looks like when it is open." …
  (close the door) … "And this is what it looks like when it is closed." Afterwards: "Is
  the garage door closed?" or "Tell me every evening at 10 pm if the garage door is still
  open."

## Operating devices

Everyday operations work by voice for everybody with the role resident or admin;
adding devices and changing credentials stays in the interface.

* "Switch off the camera in the bedroom." ✔ · "All cameras off." · "Camera back on." ✔
  *(privacy mode: no image, no sound; Tapo cameras)*
* "Stop listening in the bedroom for an hour." ✔ The room no longer reacts to "Hey
  Jarvis" and listens again automatically after the pause. "Listen again in the bedroom"
  ends the pause early (from another room or the interface).
* "The camera in the office makes no sound, reconnect it." *(takes a few seconds)*
* "Test the speaker in the kitchen." *(short tone)*
* "Stop analysing the images of the living room camera." · "… analyse them again."
  *(the camera keeps running, only the local image analysis pauses)*

## Announcements in other rooms

* "Tell the kitchen that dinner is ready."
* "Call into the children's room: dinner in five minutes!"

## Memory

* "Remember that Lucky gets food every evening at 6 pm." … later: "When does Lucky get
  food?"
* "Remember: Anna's birthday is on 3 May, she likes lilies."
* "What did I tell you about the holiday last week?"
* "What do you know about me?"
* "Forget what I told you about my job." *(shows first what will be deleted)*

The assistant also remembers important things from conversations by itself and marks
guesses as such. Review and delete: *Memory*.

## Who is speaking?

* "I am Anna."
* "Remember my face." *(asks for consent)*
* "Remember my voice." ✔ Afterwards it recognises who is speaking already by the "Hey
  Jarvis", and reminders, appointments and greetings are personal.
* "Forget my voice."

## On the screen

With a paired display, tablet or TV in the same room:

* "Show me Apple's share price over the last three months." ✔
* "How are Bitcoin, the DAX and the euro against the dollar? Show me."
* "Show me the weather for the next days."
* "Show me the garden camera." *(live image on the screen)*

## Knowledge and everyday life

* "What will the weather be like in Bolzano tomorrow?" ✔
* "How is the Tesla share doing?"
* "What is the capital of Australia?" … "Hey Jarvis, and how many people live there?" ✔
  *(continuation within 5 minutes)*
* "Briefly explain how a heat pump works."

## New abilities: the assistant writes its own plugins

If there is no tool for something, the assistant writes one: with tests and a security
review, in an isolated environment (sandbox). An admin has to approve it under *Tools*;
afterwards the assistant uses it right away.

* "I would like a function that tells me the calendar week of a date." ✔
* "Build a plugin that checks every 5 minutes whether it starts raining in Bolzano and
  tells me when it does."
  Plugins can run in the background (at most every minute), report *events* and thus
  trigger automations: "When it starts raining, tell me in the living room."
* "Build a plugin that tells me when electricity is cheaper than 20 cents."
  Needs the plugin an API key or other settings, it asks for them; the admin enters them
  under *Plugins* before it starts (status "needs settings").
* "Change the rain plugin so it also reports when the rain stops." Revises an existing
  self-made plugin; the new version is tested and approved again.
* "Which plugins have you built?" · "What can you do?"
* "Which events can I use for automations?"

## Around the system

* "Which devices are offline right now?"
* "Which cameras are there in the house?"
* "Thanks, that's all." ends the conversation (otherwise it ends by itself after a few
  seconds of silence).

## Limits

* Recognising requires that a camera sees the person or thing. Someone sitting still is
  recognised again less often; "the next time" therefore means: as soon as you come back
  into view.
* Searching a whole room only works with pan/tilt cameras; otherwise the assistant only
  sees the current image.
* Looking at and searching for arbitrary things (keys, notes, light) needs an image model,
  by default Gemini. Locally JuStAI5 recognises people, faces, animals and about 80
  everyday objects (car, bicycle, bottle, laptop, phone …).
* Cameras that mute their microphone while playing (e.g. Tapo C200) cannot be interrupted
  while the assistant speaks.
* Self-made plugins run in the sandbox: they may only reach the internet hosts named in
  their manifest and never get access to devices, the local network or the system
  configuration.
