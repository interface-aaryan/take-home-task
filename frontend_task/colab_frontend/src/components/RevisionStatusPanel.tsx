'use client';

import { useState, FormEvent } from 'react';
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

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    updateStatus(rating, comment);
    setComment('');
  };

  if (!revisionStatus) {
    return <div>Loading revision status...</div>;
  }

  // Format date for display
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-6 bg-white dark:bg-slate-800 rounded-lg shadow-md">
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-4">Current Revision Status</h2>
        <div className="flex items-center space-x-2 mb-4">
          <span className="text-lg font-medium">Rating:</span>
          <span className="text-3xl font-bold">{revisionStatus.currentStatus}/9</span>
        </div>
        
        <h3 className="text-xl font-semibold mb-2">Update History</h3>
        <div className="overflow-auto max-h-60 border border-gray-200 rounded-md p-2">
          {revisionStatus.updates.length === 0 ? (
            <p className="text-gray-500 italic">No updates yet</p>
          ) : (
            <ul className="space-y-3">
              {revisionStatus.updates.map((update, index) => (
                <li key={index} className="p-3 bg-gray-50 dark:bg-slate-700 rounded-md">
                  <div className="flex justify-between">
                    <span className="font-semibold">User: {update.userId}</span>
                    <span className="text-sm text-gray-500">{formatDate(update.timestamp)}</span>
                  </div>
                  <div className="mt-1">
                    <span className="mr-2">Rating: {update.status}/9</span>
                    {update.comment && (
                      <p className="mt-1 text-sm italic">"{update.comment}"</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {userId && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <h3 className="text-xl font-semibold">Update Revision Status</h3>
          
          <div>
            <label className="block text-sm font-medium mb-1">
              Rating (0-9)
            </label>
            <div className="flex space-x-2">
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setRating(value)}
                  className={`w-10 h-10 flex items-center justify-center rounded-md transition-colors ${
                    rating === value
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-slate-700 hover:bg-gray-200 dark:hover:bg-slate-600'
                  }`}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          
          <div>
            <label htmlFor="comment" className="block text-sm font-medium mb-1">
              Comment (optional)
            </label>
            <textarea
              id="comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none text-black dark:text-white dark:bg-slate-700"
              rows={3}
              placeholder="Add a comment about your update"
            />
          </div>
          
          <button
            type="submit"
            className="py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-md transition-colors"
          >
            Submit Update
          </button>
        </form>
      )}
    </div>
  );
}