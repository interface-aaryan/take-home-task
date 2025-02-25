# Collaborative Revision Status Application

## Overview

Imagine you're building an application where users update the a state of an important document. Each update includes details such as the reviewer's userid. Your task is to build a Next.js application using TypeScript (TSX) that enables users within the same organization to update and view the state in real time. Each user will have a unique `userId` and be associated with an organization via an `orgId` (both stored in cookies or otherwise). **Only users with the same `orgId` should be able to see and modify the state.** Users from different organizations must maintain independent states.

Interface is all about the product thinking. 

## Objectives

- **Next.js Application:**  
  Build your project using Next.js with TypeScript. Develop all components in tsx. If you really can't do it in TSX, let me know: aaryan@getinterface.ai.

- **Shared Revision Status State:**  
  Implement functionality that allows users to update a state (e.g., with a boolean indicating approval or an integer rating between 0 and 9) or more complex (e.g. text editing like in google docs). When a user updates the state, the change should be synchronized in real time for all users in the same organization, including details of all the historical reviewer's userid and timestamp.

- **Organization-Based Access Control:**  
  - Each user will have a unique `userId` and an associated `orgId` stored in cookies.
  - **Only users within the same organization (`orgId`) should see and modify the state.**
  - Users with different `orgId` values should maintain independent states and not receive cross-organization updates.

- **User Experience & Frontend Design:**  
  - **Visual Appeal:** Craft a polished, clean, and modern design that invites users to interact with the app.
  - **Responsive Layout:** Ensure the application works seamlessly across devices and screen sizes.
  - **Animations & Transitions:** Utilize subtle animations or transitions (e.g., for state changes or notifications) to enrich the user experience.
  - **Accessibility:** Keep accessibility in mind by using appropriate color contrasts, clear typography, and ensuring keyboard navigability.

## Project Setup

1. **Test the initial project:**
    - Run:
    ```bash
    cd colab_frontend
    npm install
    npm run dev
    ```
    - Open: http://localhost:3000 to view the initial project.

2. **Implement Shared Revision Status State:**
   - Set up a mechanism (e.g., Socket.IO, polling, or another method) to synchronize state changes among users in real time.
   - When a user updates the revision status, broadcast the updated state (including the reviewer's name, date, and comments) to all users in the same organization.
   - Ensure that users from different organizations (different `orgId`) have independent status values and do not receive updates across groups.

3. **Design Considerations:**
   - **Design Rationale:** Include a brief document or section in your README explaining your design decisions. What influenced your choice of colors, typography, layout, and animations? How do these choices enhance usability?

## Testing the Application

- **Development Server:**
  - The application should run using `npm run dev` (or an equivalent command), allowing evaluators to start the development server and test functionality.

- **Simulating Different Users:**
  - Open the application in multiple browser windows or tabs.
  - In each browser, set the organization ID and user ID by running the following in the console:
    ```js
    document.cookie = "orgId=your-org-id";
    document.cookie = "userId=your-user-id";
    ```
  -  The updated state should reflect in all windows sharing the same `orgId`, while users with a different `orgId` should **not** see these changes.

## Help

If you want help/guidance, please reach out to me: aaryan@getinterface.ai

## Bonus (Optional)

- **Enhanced Visual Feedback:**  
  - Implement notifications, alerts, or animations that indicate when the state is updated.
- **Stylistic Improvements:**  
  - Consider using transitions for smoother UI updates.
  - Make the app look modern and polished (as per your best judgement).

## Evaluation Criteria

Your submission will be evaluated based on:
- **Functionality:**  
  Does the shared state update work as expected in real time for users within the same organization?

- **Design Quality:**  
  Is the application visually appealing, modern, and consistent? Does it provide an excellent user experience?

- **User Experience:**  
  Are interactions intuitive? Does the app provide clear feedback and handle edge cases gracefully?

- **Clever Solutions:**  
  Are there creative or innovative approaches in both the code and the design? Did you document your design decisions?

## Good Luck!

We're excited to see your implementation that balances technical prowess with elegant frontend design and thoughtful user experience. Happy coding!
