title: Class and component annotations
package Middleware {
  component Services {
    interface IService {
      + Run()
    }
    class Service {
      - count: int
      + Run()
    }
  }
}
Service ..|> IService
note on Service: Counts successful calls.\nText such as <ready> & "done" stays literal.
note on Services width 260: Notes can also annotate a whole component.
