'use client';

import { useState, FormEvent } from 'react';

interface UserSetupProps {
  userId: string | null;
  orgId: string | null;
  setUserId: (id: string) => void;
  setOrgId: (id: string) => void;
}

export default function UserSetup({ userId, orgId, setUserId, setOrgId }: UserSetupProps) {
  const [userIdInput, setUserIdInput] = useState(userId || '');
  const [orgIdInput, setOrgIdInput] = useState(orgId || '');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (userIdInput.trim()) setUserId(userIdInput.trim());
    if (orgIdInput.trim()) setOrgId(orgIdInput.trim());
  };

  return (
    <div className="w-full max-w-md mx-auto p-6 bg-white dark:bg-slate-800 rounded-lg shadow-md">
      <h2 className="text-xl font-bold mb-4 text-center">User Information</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="userId" className="block text-sm font-medium mb-1">
            User ID
          </label>
          <input
            type="text"
            id="userId"
            value={userIdInput}
            onChange={(e) => setUserIdInput(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-black dark:text-white dark:bg-slate-700"
            placeholder="Enter your user ID"
            required
          />
        </div>
        <div>
          <label htmlFor="orgId" className="block text-sm font-medium mb-1">
            Organization ID
          </label>
          <input
            type="text"
            id="orgId"
            value={orgIdInput}
            onChange={(e) => setOrgIdInput(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-black dark:text-white dark:bg-slate-700"
            placeholder="Enter your organization ID"
            required
          />
        </div>
        <button
          type="submit"
          className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-md transition-colors"
        >
          Save
        </button>
      </form>
    </div>
  );
}