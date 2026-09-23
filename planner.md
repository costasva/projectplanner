I would like you to create a PyQt application. Use uv to manage Python for this project.

The application is a project planner. The user defines the work scope for each part of the project. That is text that is entered in a rich text window. Let's call that an activity. The application presents a rich text window for the user to endter that. Each activity has attributes such as level of effort in hours to complete. Each new activity gets a unique ID. It is possible to enter dependencies between activities by specifying the IDs of other activities that it depends on. Each activity should also have a short title. There should be a speadsheet like list of activities showing title, dependencies, total effort. The user should be able to see the full details of an activity by selecting it in that list. Also provide context menu to delete an activity.

The app should save all the data in a single file, potentially an sqlite database. It should also allow the user to export all the activities in an Excel file.

