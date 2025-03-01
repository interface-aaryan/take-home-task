# Collaborative Revision Status Application

A real-time collaborative application for maintaining and updating document revision status within organizations, built with Next.js and TypeScript.

## 🚀 Features

- **Real-time Collaboration**: Users within the same organization can see updates in real-time
- **Organization Isolation**: Each organization has its own independent revision state
- **User Authentication**: Simple user/organization identification system
- **Revision History**: Complete history of all updates with timestamps and user information
- **Rating System**: Intuitive 0-9 rating scale with optional comments
- **Modern UI**: Clean, responsive design with dark mode support

## 📋 Project Overview

This application allows users within the same organization to collaborate on document revision statuses. Each revision includes details such as:

- User ID who made the change
- Timestamp when the change was made
- A numerical rating (0-9)
- Optional comment about the change

The application ensures that only users with the same Organization ID can see and modify the shared state, creating isolation between different organizations.

## 📱 Implementation Details

The application implements a real-time collaboration system using browser storage and custom events:

- **Cross-Tab Communication**: Updates are synchronized across tabs/windows using StorageEvent
- **Organization-Based Data Isolation**: Each organization's data is stored under a unique key in localStorage
- **Real-time Updates**: Changes made by any user are immediately visible to all users in the same organization
- **State Management**: React hooks provide a clean interface for accessing and updating the shared state

## 🛠️ Technology Stack

- **Framework**: Next.js 15
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State Management**: React Hooks
- **Storage**: localStorage with custom event system for cross-tab communication
- **Deployment**: Vercel-ready

## 🏁 Getting Started

### Prerequisites

- Node.js 18+ 
- npm or yarn

### Installation

1. Clone the repository
   ```bash
   git clone <repository-url>
   cd colab_frontend
   ```

2. Install dependencies
   ```bash
   npm install
   # or
   yarn install
   ```

3. Start the development server
   ```bash
   npm run dev
   # or
   yarn dev
   ```

4. Open [http://localhost:3000](http://localhost:3000) in your browser

## 🧪 Testing the Application

To test the real-time collaboration features:

1. Open the application in multiple browser windows or tabs.

2. In each browser, set different User IDs but the same Organization ID:
   - You can do this through the UI form
   - Alternatively, you can manually set cookies in the browser console:
     ```javascript
     document.cookie = "orgId=your-org-id";
     document.cookie = "userId=your-user-id";
     ```

3. Make changes in one window and observe how they are reflected in real-time in the other windows with the same Organization ID.

4. Try with different Organization IDs to verify that the state is isolated between organizations.

## 🎨 Design Decisions

### UI/UX Design Principles

- **Clean and Minimal**: The interface focuses on content and functionality with minimal distractions
- **Visual Hierarchy**: Important information like current status and recent updates are prominently displayed
- **Consistent Design Language**: Consistent color scheme, spacing, and interaction patterns
- **Responsive**: Works seamlessly on mobile, tablet, and desktop devices
- **Accessibility**: Proper contrast ratios, semantic HTML, and keyboard navigation support
- **Dark Mode Support**: Automatically adapts to user's system preferences

### Color Scheme

- Primary: Indigo (#4F46E5) - Conveys trust, professionalism and creativity
- Background: Light with dark mode alternatives for improved readability in different environments
- Text: Dark gray on light backgrounds, light gray on dark backgrounds for optimal contrast
- Status indicators: Color-coded for quick visual recognition and feedback

### Typography

- Sans-serif font for clean, modern appearance and optimal readability
- Clear hierarchy with distinct sizes for headings and body text
- Proper line spacing and character width for comfortable reading

### Animation & Feedback

- Custom animations for state changes (fade-in, pulse-once)
- Subtle hover effects with scale transformations for interactive elements
- Visual notifications for successful updates and errors
- Loading indicators during async operations for better user experience

## 📁 Project Structure

```
colab_frontend/
├── src/
│   ├── app/           # Next.js app directory with routes
│   ├── components/    # Reusable UI components
│   │   ├── RevisionStatusPanel.tsx  # Main revision status interface
│   │   └── UserSetup.tsx            # User & organization ID setup form
│   ├── hooks/         # Custom React hooks
│   │   ├── useRevisionStatus.tsx    # Hook for managing revision state
│   │   └── useUser.tsx              # Hook for user context
│   └── utils/         # Utility functions and types
│       ├── cookies.ts              # Cookie management
│       └── types.ts                # TypeScript type definitions
├── public/            # Static assets
├── next.config.ts     # Next.js configuration
└── tailwind.config.ts # Tailwind CSS configuration
```

## 🔧 Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint for code quality

## 🚀 Deployment

This application is ready to be deployed on Vercel or any other Next.js-compatible hosting service.

## 🧩 Future Enhancements

- Server-side state management with a database
- WebSockets for more efficient real-time updates
- Enhanced authentication system
- Expanded collaborative features like comments and suggestions
- Mobile application with push notifications

## 📄 License

[MIT](LICENSE)