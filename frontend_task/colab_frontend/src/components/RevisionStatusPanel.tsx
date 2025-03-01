'use client';

import { useState, useEffect, FormEvent } from 'react';
import { RevisionStatus } from '../utils/types';

interface RevisionStatusPanelProps {
  revisionStatus: RevisionStatus | null;
  updateStatus: (newStatus: number, comment?: string) => void;
  userId: string | null;
}

export default function RevisionStatusPanel({
  revisionStatus,
  updateStatus,
  userId
}: RevisionStatusPanelProps) {
  const [rating, setRating] = useState(revisionStatus?.currentStatus || 0);
  const [comment, setComment] = useState('');
  const [notification, setNotification] = useState<{message: string, type: 'success' | 'error'} | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [lastUpdateTime, setLastUpdateTime] = useState<string | null>(null);

  // Update rating state when revisionStatus changes
  useEffect(() => {
    if (revisionStatus) {
      setRating(revisionStatus.currentStatus);
    }
  }, [revisionStatus?.currentStatus]);

  // Auto-dismiss notifications after 3 seconds
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => {
        setNotification(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  // Track the latest update timestamp
  useEffect(() => {
    if (revisionStatus?.updates.length) {
      const latestUpdate = revisionStatus.updates[revisionStatus.updates.length - 1];
      setLastUpdateTime(latestUpdate.timestamp);
    }
  }, [revisionStatus?.updates]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setIsUpdating(true);
    
    try {
      await updateStatus(rating, comment);
      setComment('');
      setNotification({ message: 'Status updated successfully!', type: 'success' });
    } catch (error) {
      setNotification({ message: 'Failed to update status.', type: 'error' });
    } finally {
      setIsUpdating(false);
    }
  };

  if (!revisionStatus) {
    return (
      <div className="w-full flex justify-center items-center p-8">
        <div className="animate-pulse flex space-x-2">
          <div className="h-3 w-3 bg-blue-600 rounded-full"></div>
          <div className="h-3 w-3 bg-blue-600 rounded-full animation-delay-200"></div>
          <div className="h-3 w-3 bg-blue-600 rounded-full animation-delay-400"></div>
        </div>
        <span className="ml-3 text-lg font-medium">Loading revision status...</span>
      </div>
    );
  }

  // Format date for display
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-6 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-gray-200 dark:border-slate-700 transition-all duration-300">
      {/* Notification */}
      {notification && (
        <div 
          className={`fixed top-4 right-4 p-4 rounded-lg shadow-lg z-50 transform transition-all duration-300 ease-out animate-fade-in ${
            notification.type === 'success' ? 'bg-green-100 text-green-800 border-l-4 border-green-500' : 'bg-red-100 text-red-800 border-l-4 border-red-500'
          }`}
        >
          <div className="flex items-center">
            <span className={`mr-2 ${notification.type === 'success' ? 'text-green-500' : 'text-red-500'}`}>
              {notification.type === 'success' ? '✓' : '✗'}
            </span>
            {notification.message}
          </div>
        </div>
      )}

      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Current Revision Status</h2>
        <div className="flex items-center space-x-2 mb-4">
          <span className="text-lg font-medium">Rating:</span>
          <div className={`text-4xl font-bold transition-all duration-500 ${
            lastUpdateTime ? 'animate-pulse-once text-indigo-600 dark:text-indigo-400' : 'text-gray-900 dark:text-white'
          }`}>
            {revisionStatus.currentStatus}
            <span className="text-2xl text-gray-500 dark:text-gray-400">/9</span>
          </div>
        </div>
        
        <h3 className="text-xl font-semibold mb-2 text-gray-800 dark:text-gray-200">Update History</h3>
        <div className="overflow-auto max-h-60 border border-gray-200 dark:border-slate-600 rounded-lg p-2 bg-gray-50 dark:bg-slate-900/50">
          {revisionStatus.updates.length === 0 ? (
            <p className="text-gray-500 dark:text-gray-400 italic p-4 text-center">No updates yet</p>
          ) : (
            <ul className="space-y-3">
              {[...revisionStatus.updates].reverse().map((update, index) => (
                <li 
                  key={index} 
                  className={`p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm border border-gray-100 dark:border-slate-700 transition-all duration-300 ${
                    index === 0 ? 'animate-fade-in' : ''
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-gray-800 dark:text-gray-200">User: {update.userId}</span>
                    <span className="text-sm text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-slate-700 px-2 py-1 rounded-full">
                      {formatDate(update.timestamp)}
                    </span>
                  </div>
                  <div className="mt-2">
                    <span className="inline-block bg-indigo-100 dark:bg-indigo-900/50 text-indigo-800 dark:text-indigo-300 px-2 py-1 rounded-md font-medium">
                      Rating: {update.status}/9
                    </span>
                    {update.comment && (
                      <p className="mt-2 text-sm italic text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-700/50 p-2 rounded-md">
                        "{update.comment}"
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {userId && (
        <form onSubmit={handleSubmit} className="space-y-4 bg-gray-50 dark:bg-slate-700/30 p-5 rounded-lg border border-gray-200 dark:border-slate-600 transition-all duration-300">
          <h3 className="text-xl font-semibold text-gray-800 dark:text-gray-200">Update Revision Status</h3>
          
          <div>
            <label className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
              Rating (0-9)
            </label>
            <div className="flex flex-wrap gap-2">
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setRating(value)}
                  className={`w-12 h-12 flex items-center justify-center rounded-lg font-medium transition-all duration-300 transform hover:scale-105 ${
                    rating === value
                      ? 'bg-indigo-600 text-white shadow-md ring-2 ring-indigo-300 dark:ring-indigo-500'
                      : 'bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700 shadow-sm'
                  }`}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          
          <div className="transition-all duration-300">
            <label htmlFor="comment" className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
              Comment (optional)
            </label>
            <textarea
              id="comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none transition-all duration-300 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500"
              rows={3}
              placeholder="Add a comment about your update"
            />
          </div>
          
          <button
            type="submit"
            disabled={isUpdating}
            className={`py-2.5 px-5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg shadow-md transition-all duration-300 transform hover:translate-y-[-1px] hover:shadow-lg flex items-center justify-center ${
              isUpdating ? 'opacity-70 cursor-not-allowed' : ''
            }`}
          >
            {isUpdating ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Processing...
              </>
            ) : (
              'Submit Update'
            )}
          </button>
        </form>
      )}
    </div>
  );
}