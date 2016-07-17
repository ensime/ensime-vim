Feature: Server bootstrap and launch
  In order to use ENSIME from my editor
  As a plugin user
  I want to have the server installed and launched automatically

  Scenario: First-time Setup
    Given no server bootstrap project exists
    And I have created a valid .ensime project config
    When I edit a Scala file
    And invoke server installation
    Then ENSIME should be installed
    And the server should be started

  Scenario: Begin an editing session with server installed
    Given I have installed ENSIME server
    And I have created a valid .ensime project config
    When I edit a Scala file
    Then the server should be started
