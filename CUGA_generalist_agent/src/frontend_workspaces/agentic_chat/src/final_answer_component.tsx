import React, { useState } from "react";

export default function FinalAnswerComponent({ answerData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);
  const [showFullAnswer, setShowFullAnswer] = useState(false);

  // Sample data - you can replace this with props

  const { thoughts, final_answer } = answerData;

  function truncateText(text, maxLength = 80) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  function getThoughtsSummary() {
    if (thoughts.length === 0) return "No analysis recorded";
    const firstThought = truncateText(thoughts[0], 100);
    return firstThought;
  }

  function getAnswerPreview(text, maxLength = 150) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  return (
    <div className="p-3">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-sm">🎯</span>
              Task Complete
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-green-100 text-green-700">
              Final Answer Ready
            </span>
          </div>

          {/* Final Answer Section */}
          <div className="mb-3 p-2 bg-green-50 rounded border border-green-200">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-sm">📋</span>
                <span className="text-xs font-medium text-green-700">Final Answer</span>
              </div>
              <button
                onClick={() => setShowFullAnswer(!showFullAnswer)}
                className="text-xs text-green-600 hover:text-green-800 bg-white px-2 py-1 rounded border"
              >
                {showFullAnswer ? "▲ Collapse" : "▼ Expand"}
              </button>
            </div>

            <div className="bg-white rounded p-2">
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                {showFullAnswer ? final_answer : getAnswerPreview(final_answer)}
              </pre>
            </div>
          </div>

          {/* Thoughts Section - Collapsible */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">💭</span>
                <span className="text-xs text-gray-500">Final Analysis ({thoughts.length})</span>
                <button
                  onClick={() => setShowFullThoughts(!showFullThoughts)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {showFullThoughts ? "▲" : "▼"}
                </button>
              </div>
            </div>
            
            {!showFullThoughts && (
              <p className="text-xs text-gray-400 italic mt-1">{getThoughtsSummary()}</p>
            )}

            {showFullThoughts && (
              <div className="mt-2 space-y-1">
                {thoughts.map((thought, index) => (
                  <div key={index} className="flex items-start gap-2">
                    <span className="text-xs text-gray-300 mt-0.5 font-mono">{index + 1}.</span>
                    <p className="text-xs text-gray-500 leading-relaxed">{thought}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
