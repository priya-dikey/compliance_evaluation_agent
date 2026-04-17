# features/cookie_consent.feature
# BDD scenarios for cookie consent compliance testing
# Derived from GDPR Art.4(11), Art.7, Recital 32, ePrivacy Directive Art.5(3)
Feature: Cookie consent banner compliance
  As a privacy compliance agent
  I want to verify the cookie consent banner meets legal requirements
  So that users' privacy rights are protected

  Background:
    Given the target site is "https://en.giesswein.com/"
    And compliance rules are loaded from secureprivacy.ai
  # ── Banner presence ───────────────────────────────────────────────────────

  Scenario: Banner appears on first visit
    Given I am a fresh visitor with no prior cookies
    When I load the homepage
    Then a cookie consent banner should be visible
    And the banner should appear before any non-essential cookies are set

  Scenario: Banner does not reappear after consent given
    Given I previously accepted all cookies
    When I reload the homepage
    Then the cookie consent banner should NOT be visible
    And my previous consent preference should be honoured

  Scenario: Banner reappears after consent expiry
    Given I accepted cookies more than 12 months ago
    When I load the homepage
    Then the cookie consent banner should be visible
    And I should be asked to re-consent
  # ── Pre-consent tracking (CRITICAL — GDPR Art.5) ─────────────────────────

  Scenario: No tracking before consent — fresh visitor
    Given I am a fresh visitor with no prior cookies
    When I load the homepage
    And I have NOT interacted with the consent banner
    Then no non-essential cookies should be set
    And no analytics or advertising network requests should fire
    And Google Analytics should NOT have loaded
    And Facebook Pixel should NOT have loaded

  Scenario: No tracking after rejection
    Given I am a fresh visitor
    When I load the homepage
    And I click "Reject All" or "Reject all" or "Decline" or "Deny" or "Only necessary" or "Use essential cookies only" on the consent banner
    Then only strictly necessary cookies should be set
    And no analytics or advertising requests should fire after rejection
  # ── Accept behaviour ──────────────────────────────────────────────────────

  Scenario: Accept all enables all cookie categories
    Given I am a fresh visitor
    When I load the homepage
    And I click "Accept All" or "Allow all" or "Agree" or "Enable cookies" on the consent banner
    Then analytics cookies should be set
    And the consent preference should be stored
    And Consent Mode v2 should fire with analytics_storage=granted
  # ── Reject behaviour (GDPR Recital 32) ───────────────────────────────────

  Scenario: Reject option is present and equally prominent
    Given I am a fresh visitor
    When I load the homepage
    Then a "Reject" or "Decline" or "Deny" or "Reject all" or "Only necessary" or "Use essential cookies only" button should be visible on the banner
    And the reject button should be reachable without scrolling
    And the reject button contrast ratio should meet WCAG AA (4.5:1)
    And the reject button should require no more clicks than accept

  Scenario: Reject all prevents all non-essential processing
    Given I am a fresh visitor
    When I click "Reject All" or "Reject all" or "Decline" or "Deny" or "Only necessary" or "Use essential cookies only"
    Then the banner should close
    And no analytics cookies should be set
    And Consent Mode v2 should fire with ad_storage=denied
  # ── Granular consent (GDPR Art.7 + Recital 43) ───────────────────────────

  Scenario: Granular consent categories are available
    Given I am a fresh visitor
    When I click "Preferences" or "Settings" on the banner
    Then I should see separate consent toggles for:
      | category  |
      | Necessary |
      | Analytics |
      | Marketing |
    And Necessary cookies should be pre-ticked and non-editable
    And Analytics and Marketing should default to OFF (opt-in)
    And I should be able to accept Analytics without accepting Marketing

  Scenario: Pre-ticked boxes are forbidden
    Given I open the cookie preferences panel
    Then no optional cookie category should be pre-ticked
    And no marketing or analytics toggle should default to ON
  # ── Consent withdrawal (GDPR Art.7(3)) ───────────────────────────────────

  Scenario: Consent can be withdrawn after acceptance
    Given I previously accepted all cookies
    When I navigate to the cookie preferences link
    Then I should be able to change my preferences
    And after withdrawing consent, analytics cookies should be deleted
    And the withdrawal process should require no more steps than giving consent
  # ── Accessibility (WCAG 2.1 AA) ───────────────────────────────────────────

  Scenario: Cookie banner is keyboard navigable
    Given I am a fresh visitor using keyboard navigation only
    When I load the homepage
    Then I should be able to Tab to the consent banner
    And Tab should reach the accept button ("Accept All", "Allow all", "Agree", or "Enable cookies")
    And Tab should reach the reject button ("Reject All", "Reject all", "Decline", "Deny", "Only necessary", or "Use essential cookies only")
    And pressing Enter or Space should activate the focused button
    And focus should be visible on all interactive elements

  Scenario: Screen reader announces banner correctly
    Given I am using a screen reader
    When the cookie consent banner appears
    Then the banner should have role="dialog" or aria-modal="true"
    And the banner heading should be announced
    And all buttons should have descriptive accessible names
    And the purpose of each button should be clear from audio alone
  # ── Consent Mode v2 (Google tags) ─────────────────────────────────────────

  Scenario: Consent Mode v2 defaults to denied
    Given Google Tag Manager is loaded on the site
    When I load the homepage as a fresh visitor
    Then window.dataLayer should contain a consent default push
    And ad_storage should default to "denied"
    And analytics_storage should default to "denied"

  Scenario: Consent Mode v2 updates on accept
    Given Google Tag Manager is loaded
    When I accept analytics cookies only
    Then dataLayer should receive a consent update push
    And analytics_storage should be "granted"
    And ad_storage should remain "denied"
