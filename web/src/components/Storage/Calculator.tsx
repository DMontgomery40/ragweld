// Storage Calculator - Main Container Component
// Coordinates between Calculator 1 (Full Requirements) and Calculator 2 (Optimization)

import React, { useState } from 'react';
import { useStorageCalculator, useOptimizationCalculator } from '@/hooks/useStorageCalculator';
import { CalculatorForm } from './CalculatorForm';
import { ResultsDisplay } from './ResultsDisplay';
import { OptimizationPlan } from './OptimizationPlan';

export function Calculator() {
  // State for which calculator is active
  const [activeTab, setActiveTab] = useState<'full' | 'optimize'>('full');

  // Calculator 1: Full Storage Requirements
  const calc1 = useStorageCalculator();

  // Calculator 2: Optimization & Fitting (shares inputs from calc1)
  const calc2 = useOptimizationCalculator(calc1.inputs);

  return (
    <div className="storage-calculator" style={{ padding: '20px', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '8px' }}>
          Storage Calculator
        </h1>
        <p style={{ color: '#666', fontSize: '14px' }}>
          Calculate exact storage requirements and explore optimization strategies
        </p>
      </div>

      {/* Tab Navigation */}
      <div style={{
        display: 'flex',
        gap: '8px',
        borderBottom: '2px solid #e5e7eb',
        marginBottom: '24px'
      }}>
        <button
          onClick={() => setActiveTab('full')}
          style={{
            padding: '12px 24px',
            fontSize: '14px',
            fontWeight: '600',
            border: 'none',
            borderBottom: activeTab === 'full' ? '3px solid #3b82f6' : '3px solid transparent',
            background: 'transparent',
            color: activeTab === 'full' ? '#3b82f6' : '#6b7280',
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
          aria-label="Full Requirements Calculator"
          aria-selected={activeTab === 'full'}
          role="tab"
        >
          Full Requirements
        </button>
        <button
          onClick={() => setActiveTab('optimize')}
          style={{
            padding: '12px 24px',
            fontSize: '14px',
            fontWeight: '600',
            border: 'none',
            borderBottom: activeTab === 'optimize' ? '3px solid #3b82f6' : '3px solid transparent',
            background: 'transparent',
            color: activeTab === 'optimize' ? '#3b82f6' : '#6b7280',
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
          aria-label="Optimization Calculator"
          aria-selected={activeTab === 'optimize'}
          role="tab"
        >
          Optimization
        </button>
      </div>

      {/* Calculator 1: Full Requirements */}
      {activeTab === 'full' && (
        <div className="calculator-full" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
          {/* Left: Input Form */}
          <div style={{
            background: '#ffffff',
            padding: '24px',
            borderRadius: '8px',
            border: '1px solid #e5e7eb',
            height: 'fit-content'
          }}>
            <h2 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px' }}>
              Configuration
            </h2>
            <CalculatorForm
              inputs={calc1.inputs}
              onUpdate={calc1.updateInput}
              mode="full"
            />
          </div>

          {/* Right: Results */}
          <div style={{
            background: '#ffffff',
            padding: '24px',
            borderRadius: '8px',
            border: '1px solid #e5e7eb',
            height: 'fit-content'
          }}>
            <h2 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px' }}>
              Storage Requirements
            </h2>
            <ResultsDisplay results={calc1.results} />
          </div>
        </div>
      )}

      {/* Calculator 2: Optimization */}
      {activeTab === 'optimize' && (
        <div className="calculator-optimize">
          {/* Optimization Inputs */}
          <div style={{
            background: '#ffffff',
            padding: '24px',
            borderRadius: '8px',
            border: '1px solid #e5e7eb',
            marginBottom: '24px'
          }}>
            <h2 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px' }}>
              Target Budget & Configuration
            </h2>
            <CalculatorForm
              inputs={calc2.inputs}
              onUpdate={calc2.updateInput}
              mode="optimize"
            />
          </div>

          {/* Optimization Plans */}
          <OptimizationPlan results={calc2.results} />
        </div>
      )}

      {/* Info Footer */}
      <div style={{
        marginTop: '32px',
        padding: '16px',
        background: '#f9fafb',
        borderRadius: '8px',
        fontSize: '13px',
        color: '#6b7280'
      }}>
        <p style={{ marginBottom: '8px' }}>
          <strong>Note:</strong> Both calculators share common parameters from the Full Requirements configuration.
        </p>
        <p>
          Calculator 1 (Full Requirements) provides exact storage calculations.
          Calculator 2 (Optimization) explores compression strategies to fit within a target budget.
        </p>
      </div>
    </div>
  );
}
