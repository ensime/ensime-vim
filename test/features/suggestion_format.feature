Feature: Format a Completion Suggestion
  In order to show suggestions in completion popup
  We need to format them depending on the Scala Type

  Scenario Outline: Format parameter type
    Given Parameter type with name <type_name>
    When We format the type
    Then We get the format <type_format>

  Examples:
    | type_name              | type_format   |
    | ParamType              | ParamType     |
    | <byname>[ByNameType]   | => ByNameType |
    | <repeated>[VarargType] | VarargType*   |

  Scenario: Format empty parameters
    Given A list of parameters:
      | pname   | ptype |
    When We concat the parameters
    Then We get the empty string 

  Scenario: Format single parameter
    Given A list of parameters:
      | pname   | ptype |
      | someInt | Int   |
    When We concat the parameters
    Then We get the format someInt: Int

  Scenario: Format multiple parameters
    Given A list of parameters:
      | pname      | ptype          |
      | someLong   | Long           |
      | someBool   | Boolean        |
      | someOption | Option[String] |
    When We concat the parameters
    Then We get the format someLong: Long, someBool: Boolean, someOption: Option[String]

  Scenario: Format empty parameters section
    Given A list of parameters:
      | pname   | ptype |
    And The section is not implicit
    When We format the section
    Then We get the format ()

  Scenario: Format parameters section
    Given A list of parameters:
      | pname | ptype |
      | a     | A     |
      | b     | B     |
    And The section is not implicit
    When We format the section
    Then We get the format (a: A, b: B)

  Scenario: Format implicit parameters section
    Given A list of parameters:
      | pname | ptype |
      | a     | A     |
      | b     | B     |
    And The section is implicit
    When We format the section
    Then We get the format (implicit a: A, b: B)

  Scenario Outline: Format completion type
    Given Completion with typehint <typehint>
    And TypeInfo with type <ctype>
    And TypeInfo with resultType <crtype>
    When We format the completion type
    Then We get the format <ctype_format>

  Examples:
    | typehint      | ctype     | crtype        | ctype_format  |
    | BasicTypeInfo | TheType   | NotUsed       | TheType       |
    | ArrowTypeInfo | ACallable | TheResultType | TheResultType |

  Scenario: Format non-callable completion signature
    Given Completion with typehint BasicTypeInfo
    And Name is nonCallable
    And Sections:
      | implicit | pname | ptype |
    When We format the signature
    Then We get the format nonCallable

  Scenario: Format non-params-callable completion signature
    Given Completion with typehint ArrowTypeInfo
    And Name is nonParamsCallable
    And Sections:
      | implicit | pname | ptype |
    When We format the signature
    Then We get the format nonParamsCallable

  Scenario: Format callable completion signature
    Given Completion with typehint ArrowTypeInfo
    And Name is theCallable
    And Sections:
      | implicit | pname | ptype |
      | False    | a     | A     |
      | True     | b     | B     |
    When We format the signature
    Then We get the format theCallable(a: A)(implicit b: B)

  Scenario: Convert completions to suggestions
    Given We have the following completions:
      | name              | typehint      | ctype        | crtype        | pname | ptype | implicit |
      | nonCallable       | BasicTypeInfo | SomeType     |               |       |       |          |
      | nonParamsCallable | ArrowTypeInfo | OtherType    | TheResultType |       |       |          |
      | theCallable       | ArrowTypeInfo | CallableType | TheResultType | a     | A     | False    |
    When We convert completions to suggestions
    Then We get the following suggestions:
      | word              | abbr              | menu          |
      | nonCallable       | nonCallable       | SomeType      |
      | nonParamsCallable | nonParamsCallable | TheResultType |
      | theCallable       | theCallable(a: A) | TheResultType |

