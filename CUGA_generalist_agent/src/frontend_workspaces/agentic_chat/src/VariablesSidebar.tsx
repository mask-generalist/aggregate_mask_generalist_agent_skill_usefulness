import React, { useState } from "react";
import VariablePopup from "./VariablePopup";
import "./VariablesSidebar.css";

interface VariablesHistoryItem {
  id: string;
  title: string;
  timestamp: number;
  variables: Record<string, any>;
}

interface VariablesSidebarProps {
  variables: Record<string, any>;
  history?: VariablesHistoryItem[];
  selectedAnswerId?: string | null;
  onSelectAnswer?: (answerId: string) => void;
}

const VariablesSidebar: React.FC<VariablesSidebarProps> = ({ 
  variables, 
  history = [],
  selectedAnswerId,
  onSelectAnswer 
}) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [selectedVariable, setSelectedVariable] = useState<any>(null);
  const variableKeys = Object.keys(variables);

  console.log('VariablesSidebar render - variableKeys:', variableKeys.length, 'history:', history.length, 'selectedAnswerId:', selectedAnswerId);

  if (variableKeys.length === 0 && history.length === 0) {
    console.log('VariablesSidebar: No variables or history, not rendering');
    return null;
  }

  // Always show sidebar if there's history, even if no current variables
  const shouldShowSidebar = variableKeys.length > 0 || history.length > 0;

  const formatTimestamp = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <>
      <div className={`variables-sidebar ${isExpanded ? 'expanded' : 'collapsed'}`}>
        <div className="variables-sidebar-header">
          <button
            className="variables-sidebar-toggle"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? "Collapse variables panel" : "Expand variables panel"}
          >
            {isExpanded ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15 18 9 12 15 6"></polyline>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            )}
          </button>
          {isExpanded && (
            <>
              <div className="variables-sidebar-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 7h16M4 12h16M4 17h16"></path>
                </svg>
                <span>Variables</span>
                <span className="variables-count">{variableKeys.length}</span>
              </div>
              {history.length > 0 && (
                <select
                  className="variables-history-select"
                  value={selectedAnswerId || ''}
                  onChange={(e) => onSelectAnswer && onSelectAnswer(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  title="Select which conversation turn to view variables from"
                >
                  {history.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title} - {Object.keys(item.variables).length} variable{Object.keys(item.variables).length !== 1 ? 's' : ''} ({formatTimestamp(item.timestamp)})
                    </option>
                  ))}
                </select>
              )}
            </>
          )}
        </div>

        {isExpanded && (
          <div className="variables-sidebar-content">
            {history.length > 0 && (
              <div className="variables-history-info">
                Viewing: {history.find(h => h.id === selectedAnswerId)?.title || 'Latest turn'}
                <span className="history-count">{history.length} turns total</span>
              </div>
            )}
            <div className="variables-list">
              {variableKeys.length === 0 && history.length > 0 ? (
                <div className="no-variables-message">
                  <p>No variables in current turn.</p>
                  <p>Select a previous turn from the dropdown above to view its variables.</p>
                </div>
              ) : (
                variableKeys.map((varName) => {
                  const variable = variables[varName];
                  return (
                    <div
                      key={varName}
                      className="variable-item"
                      onClick={() => setSelectedVariable({ name: varName, ...variable })}
                    >
                      <div className="variable-item-header">
                        <code className="variable-name">{varName}</code>
                        <span className="variable-type">{variable.type}</span>
                      </div>
                      {variable.description && (
                        <div className="variable-description">{variable.description}</div>
                      )}
                      {variable.count_items !== undefined && variable.count_items > 1 && (
                        <div className="variable-meta">
                          <span className="variable-count">{variable.count_items} items</span>
                        </div>
                      )}
                      <div className="variable-preview">
                        {variable.value_preview
                          ? variable.value_preview.substring(0, 80) + (variable.value_preview.length > 80 ? "..." : "")
                          : ""}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>

      {/* Floating toggle button when sidebar is collapsed */}
      {!isExpanded && (
        <button
          className="variables-sidebar-floating-toggle"
          onClick={() => setIsExpanded(true)}
          title="Show variables panel"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
          <span className="variables-floating-count">{variableKeys.length}</span>
        </button>
      )}

      {selectedVariable && (
        <VariablePopup
          variable={selectedVariable}
          onClose={() => setSelectedVariable(null)}
        />
      )}
    </>
  );
};

export default VariablesSidebar;

