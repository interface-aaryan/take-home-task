'use client';

import { useUser } from '../hooks/useUser';
import { useRevisionStatus } from '../hooks/useRevisionStatus';
import UserSetup from '../components/UserSetup';
import RevisionStatusPanel from '../components/RevisionStatusPanel';

export default function Home() {
  const { userId, orgId, isLoading, setUserId, setOrgId } = useUser();
  const { revisionStatus, updateStatus } = useRevisionStatus(orgId, userId);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white">
      <header className="bg-white dark:bg-slate-800 shadow-sm">
        <div className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold">Collaborative Revision Status</h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
        {isLoading ? (
          <div className="flex justify-center items-center h-64">
            <p>Loading...</p>
          </div>
        ) : !userId || !orgId ? (
          <div className="mb-8">
            <UserSetup
              userId={userId}
              orgId={orgId}
              setUserId={setUserId}
              setOrgId={setOrgId}
            />
            <div className="mt-6 text-center text-sm text-gray-600 dark:text-gray-400">
              <p>
                Please set your User ID and Organization ID to continue.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            <div className="bg-white dark:bg-slate-800 shadow-sm rounded-lg p-4">
              <div className="flex justify-between items-center">
                <div>
                  <span className="block text-sm font-medium text-gray-500 dark:text-gray-400">
                    Logged in as
                  </span>
                  <span className="block font-medium">{userId}</span>
                </div>
                <div>
                  <span className="block text-sm font-medium text-gray-500 dark:text-gray-400">
                    Organization
                  </span>
                  <span className="block font-medium">{orgId}</span>
                </div>
                <button
                  onClick={() => {
                    setUserId('');
                    setOrgId('');
                  }}
                  className="px-3 py-1 text-sm bg-gray-100 dark:bg-slate-700 hover:bg-gray-200 dark:hover:bg-slate-600 rounded-md transition-colors"
                >
                  Change User
                </button>
              </div>
            </div>

            <RevisionStatusPanel
              revisionStatus={revisionStatus}
              updateStatus={updateStatus}
              userId={userId}
            />
            
            <div className="mt-6 text-center text-sm text-gray-600 dark:text-gray-400">
              <p>
                Open this page in another browser window/tab and set the same Organization ID
                to see real-time updates between users in the same organization.
              </p>
              <p className="mt-2">
                Set a different Organization ID to see that each organization has its own
                independent state.
              </p>
            </div>
          </div>
        )}
      </main>

      <footer className="bg-white dark:bg-slate-800 mt-8">
        <div className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8 text-center text-sm text-gray-500 dark:text-gray-400">
          <p>Collaborative Revision Status Application</p>
        </div>
      </footer>
    </div>
  );
}
