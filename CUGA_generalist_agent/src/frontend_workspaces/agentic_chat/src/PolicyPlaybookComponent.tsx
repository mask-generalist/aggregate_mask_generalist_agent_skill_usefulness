import React from "react";
import { BookOpen, Info, Lightbulb } from "lucide-react";
import "./PolicyPlaybookComponent.css";

interface PolicyPlaybookData {
  type: "policy_playbook";
  content: string;
  metadata: {
    policy_matched: boolean;
    policy_id: string;
    policy_name: string;
    policy_type: string;
    policy_confidence: number;
    playbook_guidance?: string;
    playbook_steps?: Array<{
      step_number: number;
      instruction: string;
      expected_outcome: string;
      tools_allowed?: string[];
    }>;
  };
}

interface PolicyPlaybookComponentProps {
  data: PolicyPlaybookData;
}

const PolicyPlaybookComponent: React.FC<PolicyPlaybookComponentProps> = ({ data }) => {
  const { content, metadata } = data;
  const confidencePercent = Math.round(metadata.policy_confidence * 100);
  const steps = metadata.playbook_steps || [];

  return (
    <div className="policy-playbook-container">
      <div className="policy-playbook-header">
        <div className="policy-playbook-icon">
          <BookOpen size={24} />
        </div>
        <div className="policy-playbook-title">
          <h3>Playbook Activated</h3>
          <span className="policy-playbook-badge">Guided Workflow</span>
        </div>
      </div>

      <div className="policy-playbook-content">
        <div className="policy-playbook-message">
          <Lightbulb size={18} className="message-icon" />
          <p>{content || "I'll guide you through this process step by step."}</p>
        </div>

        <div className="policy-playbook-details">
          <div className="policy-detail-row">
            <span className="policy-detail-label">Playbook Name:</span>
            <span className="policy-detail-value">{metadata.policy_name}</span>
          </div>
          
          <div className="policy-detail-row">
            <span className="policy-detail-label">Policy ID:</span>
            <span className="policy-detail-value policy-id">{metadata.policy_id}</span>
          </div>
          
          <div className="policy-detail-row">
            <span className="policy-detail-label">Match Confidence:</span>
            <div className="confidence-bar-container">
              <div className="confidence-bar">
                <div 
                  className="confidence-bar-fill" 
                  style={{ width: `${confidencePercent}%` }}
                />
              </div>
              <span className="confidence-value">{confidencePercent}%</span>
            </div>
          </div>

          {steps.length > 0 && (
            <div className="playbook-steps-section">
              <div className="steps-header">
                <Info size={16} />
                <span>Workflow Steps ({steps.length})</span>
              </div>
              <div className="steps-list">
                {steps.map((step, index) => (
                  <div key={index} className="step-item">
                    <div className="step-number">{step.step_number}</div>
                    <div className="step-content">
                      <div className="step-instruction">{step.instruction}</div>
                      {step.expected_outcome && (
                        <div className="step-outcome">
                          <span className="outcome-label">Expected:</span> {step.expected_outcome}
                        </div>
                      )}
                      {step.tools_allowed && step.tools_allowed.length > 0 && (
                        <div className="step-tools">
                          <span className="tools-label">Tools:</span> {step.tools_allowed.join(", ")}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {metadata.playbook_guidance && (
            <div className="playbook-guidance-section">
              <div className="guidance-header">
                <Info size={16} />
                <span>Guidance</span>
              </div>
              <div className="guidance-text">{metadata.playbook_guidance}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PolicyPlaybookComponent;

