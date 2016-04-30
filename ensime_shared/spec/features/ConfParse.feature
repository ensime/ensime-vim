Feature: Load Config File
  In order to run Ensime
  We need to load a config file

  Scenario: Parse Config Name
    Given There is an existing ensime config resources/test.conf
    When We load the config
    Then We extract the name testing

  Scenario: Parse Scala Version
    Given There is an existing ensime config resources/test.conf
    When We load the config
    Then We extract the scala version 2.11.8

  Scenario: Parse Arbitrarily Nested SExp
    Given There is an existing ensime config resources/test.conf
    When we load the config
    Then We can parse nested expressions

