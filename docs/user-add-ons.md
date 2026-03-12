1. We should ensure Embedding Model and indexing safety. Say two agents working at the same time attempt to index two separate workspaces. SHould should build safety into it where it responds that the server is currently in-use performing the initial index of a codebase, and to please try again later. To ensure users aren't running into resources issues. We need to make sure incremental indexing after doesn't cause issues though. We wouldn't want to block on that, only for this initial index which is very resource intensive. ANd we're running locally. We just want to ensure this package isn't going to cause a users PC to freeze up if multiple AI agents bombard it at once.

- For this, do we need to potentially look into leveraging something like VLLM to host and run the models? Or is our current setup already fine as is? Does vLLM integration outperform our current setup? How big of a change would this be? 


2. We should look into expanding our language support a bit further to ensure we're covering the popular coding languages. Here is a reference resource:

- https://tree-sitter.github.io/tree-sitter/


3. We should investigate if our Tree Sitter setup is accurate and should suffice for our file types. We should review if there are more accurate setups for files like TOML, JSON, etc. The following reference resources can be used in this investigation:

- https://tree-sitter.github.io/tree-sitter/
- https://github.com/tree-sitter/tree-sitter/wiki/List-of-parsers

Right now I'm not sure if our toml indexing is actually working correctly or as good as it should, so we should definitely investigate and make sure our toml, json, and yaml setups are correct. As well as Kotlin. We should also make sure that it's able to handle different Java JDK versions. For example, my Kotlin server runs on JDK 21+, Java 25 LTS, while my client for the server runs on JDK 11, so we need to ensure this codebase can handle both of those. Essentially I want to investigate that our tree sitter logic is well built out and should cover the different languages we have defined.